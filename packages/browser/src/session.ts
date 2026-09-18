import {
  AsyncDuckDB,
  type AsyncDuckDBConnection,
  type DuckDBBundles,
  DuckDBDataProtocol,
  getJsDelivrBundles,
  selectBundle,
  VoidLogger,
} from "@duckdb/duckdb-wasm";
import { CompiledModel, type GivenValue, type Inspection } from "@pymalloy/core";

import { type File, type Files, modelURL, snapshot, readImport } from "./files.js";
import { materialize, type ResultRow } from "./arrow.js";

export interface SessionOptions {
  bundles?: DuckDBBundles;
  signal?: AbortSignal;
}
export interface ModelOptions {
  files?: Files;
  url?: string;
  imports?: Readonly<Record<string, string>>;
}
export interface RunOptions extends ModelOptions {
  query?: string;
  givens?: Record<string, GivenValue>;
}
export interface Result {
  queries: readonly string[];
  sql: string;
  columns: Array<{ name: string; type: string }>;
  rows: ResultRow[];
}
export interface Model {
  readonly queries: readonly string[];
  inspect(): Inspection;
  run(options?: Omit<RunOptions, keyof ModelOptions>): Promise<Result>;
  run(source: string, options?: Omit<RunOptions, keyof ModelOptions>): Promise<Result>;
  close(): void;
}

export class Session {
  private readonly models = new Set<SessionModel>();
  private pending: Promise<unknown> = Promise.resolve();
  private stopped = false;
  private closing?: Promise<void>;
  private activeFiles: string[] = [];
  private activeSnapshot?: Map<string, File>;
  private readonly imports = new AbortController();

  private constructor(
    private readonly database: AsyncDuckDB,
    private readonly connection: AsyncDuckDBConnection,
    private readonly worker: Worker,
    private readonly failure: Promise<never>,
    private readonly fail: (error: Error) => void,
    private readonly removeAbortListener: () => void,
  ) {}

  static async create(options: SessionOptions = {}): Promise<Session> {
    const signal = options.signal;
    const bundles = structuredClone(options.bundles ?? getJsDelivrBundles());
    signal?.throwIfAborted();
    let workerURL: string | undefined;
    let worker: Worker | undefined;
    let database: AsyncDuckDB | undefined;
    let rejectFailure!: (error: Error) => void;
    const failure = new Promise<never>((_, reject) => {
      rejectFailure = reject;
    });
    void failure.catch(() => undefined);
    const abort = () =>
      rejectFailure(
        signal?.reason instanceof Error
          ? signal.reason
          : new DOMException("Session was aborted", "AbortError"),
      );
    const removeAbortListener = () => signal?.removeEventListener("abort", abort);
    signal?.addEventListener("abort", abort, { once: true });
    try {
      const bundle = await Promise.race([selectBundle(bundles), failure]);
      signal?.throwIfAborted();
      if (!bundle.mainWorker) throw new Error("The selected DuckDB bundle has no worker");
      workerURL = URL.createObjectURL(
        new Blob([`importScripts(${JSON.stringify(bundle.mainWorker)});`], {
          type: "text/javascript",
        }),
      );
      worker = new Worker(workerURL);
      database = new AsyncDuckDB(new VoidLogger(), worker);
      worker.addEventListener("error", (event) =>
        rejectFailure(new Error(event.message || "DuckDB worker failed")),
      );
      worker.addEventListener("messageerror", () =>
        rejectFailure(new Error("DuckDB worker message failed")),
      );
      await Promise.race([database.instantiate(bundle.mainModule, bundle.pthreadWorker), failure]);
      await Promise.race([
        database.open({
          query: {
            castBigIntToDouble: false,
            castDecimalToDouble: false,
            castTimestampToDate: false,
          },
          arrowLosslessConversion: true,
        }),
        failure,
      ]);
      const connection = await Promise.race([database.connect(), failure]);
      await Promise.race([connection.query("SET TimeZone='UTC'"), failure]);
      const session = new Session(
        database,
        connection,
        worker,
        failure,
        rejectFailure,
        removeAbortListener,
      );
      void failure.catch(() => session.close());
      return session;
    } catch (error) {
      removeAbortListener();
      try {
        await database?.terminate();
      } finally {
        worker?.terminate();
      }
      throw error;
    } finally {
      if (workerURL) URL.revokeObjectURL(workerURL);
    }
  }

  get closed(): boolean {
    return this.stopped;
  }

  model(source: string, options: ModelOptions = {}): Promise<Model> {
    const files = snapshot(options.files);
    const definition = structuredClone({ url: options.url, imports: options.imports });
    return this.enqueue(async () => {
      const compiled = await this.compile(source, files, definition);
      if (this.stopped) throw new Error("Session is closed");
      const model = new SessionModel(
        compiled.queries,
        (extension, selected) =>
          this.enqueue(async () => {
            await this.activate(files);
            return this.execute(compiled, selected, extension);
          }),
        () => {
          if (this.closed) throw new Error("Session is closed");
          return compiled.inspect();
        },
        () => {
          this.models.delete(model);
          if (this.activeSnapshot === files) this.activeSnapshot = undefined;
        },
      );
      this.models.add(model);
      return model;
    });
  }

  run(source: string, options: RunOptions = {}): Promise<Result> {
    const files = snapshot(options.files);
    const definition = structuredClone({ url: options.url, imports: options.imports });
    const selected = structuredClone({ query: options.query, givens: options.givens });
    return this.enqueue(async () => {
      const compiled = await this.compile(source, files, definition);
      return this.execute(compiled, selected);
    });
  }

  close(): Promise<void> {
    if (!this.closing) {
      this.stopped = true;
      for (const model of this.models) model.close();
      this.removeAbortListener();
      this.imports.abort();
      this.activeSnapshot = undefined;
      this.activeFiles = [];
      this.fail(new Error("Session is closed"));
      this.closing = this.database.terminate().finally(() => this.worker.terminate());
    }
    return this.closing;
  }

  private enqueue<T>(task: () => Promise<T>): Promise<T> {
    if (this.stopped) return Promise.reject(new Error("Session is closed"));
    const result = this.pending.then(() => {
      if (this.stopped) throw new Error("Session is closed");
      return Promise.race([task(), this.failure]);
    });
    this.pending = result.catch(() => undefined);
    return result;
  }

  private async activate(files: Map<string, File>): Promise<void> {
    if (this.activeSnapshot === files) return;
    this.activeSnapshot = undefined;
    for (const name of this.activeFiles) await this.database.dropFile(name);
    this.activeFiles = [];
    for (const [name, file] of files) {
      if (file instanceof Uint8Array) await this.database.registerFileBuffer(name, file.slice());
      else await this.database.registerFileURL(name, file.url, DuckDBDataProtocol.HTTP, true);
      this.activeFiles.push(name);
    }
    this.activeSnapshot = files;
  }

  private async compile(
    source: string,
    files: Map<string, File>,
    options: Pick<ModelOptions, "url" | "imports">,
  ): Promise<CompiledModel> {
    await this.activate(files);
    const root = new URL(options.url ?? modelURL);
    return CompiledModel.load({
      url: root,
      source,
      describe: async (sql) => {
        const result = await this.connection.query(`DESCRIBE ${sql}`);
        return result
          .toArray()
          .map((row) => ({ name: String(row.column_name), type: String(row.column_type) }));
      },
      readURL: async (url) => {
        if (options.imports === undefined) return readImport(files, url, this.imports.signal, root);
        if (!Object.hasOwn(options.imports, url.href)) {
          throw new Error(`Import '${url.href}' is not present in captured source`);
        }
        return options.imports[url.href];
      },
    });
  }

  private async execute(
    compiled: CompiledModel,
    options: RunOptions,
    extension?: string,
  ): Promise<Result> {
    const query = await compiled.query(options.query, extension, options.givens);
    const table = await this.connection.query(query.sql);
    return {
      queries: [...compiled.queries],
      sql: query.sql,
      ...materialize(table),
    };
  }
}

function querySource(value: string | Omit<RunOptions, keyof ModelOptions>): value is string {
  return typeof value === "string";
}

class SessionModel implements Model {
  constructor(
    readonly queries: readonly string[],
    private execute:
      | ((
          source: string | undefined,
          options: Omit<RunOptions, keyof ModelOptions>,
        ) => Promise<Result>)
      | undefined,
    private describe: (() => Inspection) | undefined,
    private release: (() => void) | undefined,
  ) {}

  inspect(): Inspection {
    if (!this.describe) throw new Error("Model is closed");
    return this.describe();
  }

  run(options?: Omit<RunOptions, keyof ModelOptions>): Promise<Result>;
  run(source: string, options?: Omit<RunOptions, keyof ModelOptions>): Promise<Result>;
  run(
    sourceOrOptions: string | Omit<RunOptions, keyof ModelOptions> = {},
    options: Omit<RunOptions, keyof ModelOptions> = {},
  ): Promise<Result> {
    if (!this.execute) return Promise.reject(new Error("Model is closed"));
    const extension = querySource(sourceOrOptions) ? sourceOrOptions : undefined;
    const selected = structuredClone(querySource(sourceOrOptions) ? options : sourceOrOptions);
    if (extension !== undefined && selected.query !== undefined) {
      return Promise.reject(new Error("Choose source or query"));
    }
    return this.execute(extension, selected);
  }

  close(): void {
    this.execute = undefined;
    this.describe = undefined;
    this.release?.();
    this.release = undefined;
  }
}

export type { DuckDBBundles, GivenValue };
