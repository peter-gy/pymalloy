import { materialize } from "@malloy-runtime/duckdb/arrow";
import { checkSource, formatSource } from "@malloy-runtime/compiler/tooling";
import {
  AsyncDuckDB,
  type AsyncDuckDBConnection,
  type DuckDBBundles,
  DuckDBDataProtocol,
  getJsDelivrBundles,
  selectBundle,
  VoidLogger,
} from "@duckdb/duckdb-wasm";
import {
  CompiledModel,
  Model,
  Operations,
  ToolingError,
  type OperationOptions,
  type RunOptions,
  type SourcePosition,
  type ModelSource,
  type Column,
} from "@malloy-runtime/compiler";
import {
  connection as compilerConnection,
  drive,
  stableResult,
  type Host,
} from "@malloy-runtime/duckdb";
import { type File, type Files, modelURL, snapshot, readImport } from "./files.js";

export interface SessionOptions {
  bundles?: DuckDBBundles;
  signal?: AbortSignal;
}
export type ModelSpec = (
  | { text: string; url?: string }
  | { source: ModelSource }
  | { url: string }
) & { files?: Files };
export class Session {
  private readonly models = new Set<Model>();
  private readonly operations: Operations;
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
  ) {
    this.operations = new Operations(() => {
      this.fail(new Error("Active operation was cancelled"));
      void this.close();
    });
  }

  static async open(options: SessionOptions = {}): Promise<Session> {
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

  model(input: ModelSpec, options: OperationOptions = {}): Promise<Model> {
    const { files: inputFiles, ...definition } = input;
    const files = snapshot(inputFiles);
    const spec = structuredClone(definition);
    return this.enqueue(async () => {
      await this.activate(files);
      const captured = "source" in spec ? spec.source : undefined;
      const root = new URL(captured?.url ?? ("url" in spec ? (spec.url ?? modelURL) : modelURL));
      const host = this.host(files, root, captured);
      const compiled = await drive(
        CompiledModel.begin({
          url: root,
          source: captured?.text ?? ("text" in spec ? spec.text : undefined),
          connection: compilerConnection,
        }),
        host,
      );
      if (this.stopped) throw new Error("Session is closed");
      const schemas = new Map<string, { signature: string; columns: Column[] }>();
      const model = new Model(compiled, {
        assertActive: () => {
          if (this.stopped) throw new Error("Session is closed");
        },
        compile: (job) => drive(job, host),
        run: async (sql, template) => {
          const table = await this.connection.query(sql);
          const data = materialize(table);
          const signature = JSON.stringify(table.schema, (_key, value) =>
            value instanceof Map ? [...value] : value,
          );
          const cached = schemas.get(sql);
          const reusable =
            table.schema.dictionaries.size === 0 && sql.length + signature.length <= 65_536;
          let columns = reusable && cached?.signature === signature ? cached.columns : undefined;
          if (!columns) {
            columns = await host.describe(sql);
            if (reusable) {
              if (schemas.size === 32) schemas.delete(schemas.keys().next().value!);
              schemas.set(sql, { signature, columns });
            }
          }
          return {
            sql,
            rows: data.rows,
            columns: structuredClone(columns),
            malloy: stableResult(sql, columns, data.rows, template),
          };
        },
        submit: (task, options) =>
          this.enqueue(async () => {
            await this.activate(files);
            return task();
          }, options),
        release: () => {
          this.models.delete(model);
          if (this.activeSnapshot === files) this.activeSnapshot = undefined;
        },
      });
      this.models.add(model);
      return model;
    }, options);
  }
  async run(text: string, options: RunOptions & { files?: Files } = {}) {
    const captured = { givens: structuredClone(options.givens), signal: options.signal };
    const model = await this.model({ text, files: options.files }, captured);
    try {
      return await model.query().run(captured);
    } finally {
      model.close();
    }
  }
  check(
    text: string,
    options: {
      files?: Files;
      url?: string;
      syntaxOnly?: boolean;
      position?: SourcePosition;
    } & OperationOptions = {},
  ) {
    const files = snapshot(options.files);
    const root = new URL(options.url ?? modelURL);
    return this.enqueue(async () => {
      await this.activate(files);
      return drive(
        checkSource({
          url: root,
          source: text,
          connection: compilerConnection,
          syntaxOnly: options.syntaxOnly,
          position: options.position,
        }),
        this.host(files, root),
      );
    }, options);
  }
  format(text: string) {
    const result = formatSource(text);
    if (result.diagnostics.length)
      throw new ToolingError("Malloy formatting failed", result.diagnostics);
    return result.source;
  }

  close(): Promise<void> {
    if (!this.closing) {
      this.stopped = true;
      void this.operations.close();
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

  private enqueue<T>(task: () => Promise<T>, options: OperationOptions = {}): Promise<T> {
    if (this.stopped) return Promise.reject(new Error("Session is closed"));
    return this.operations.run(() => Promise.race([task(), this.failure]), options);
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

  private host(files: Map<string, File>, root: URL, captured?: ModelSource): Host {
    return {
      describe: async (sql) => {
        const result = await this.connection.query(`DESCRIBE ${sql}`);
        return result
          .toArray()
          .map((row) => ({ name: String(row.column_name), type: String(row.column_type) }));
      },
      readURL: async (url) => {
        if (!captured) return readImport(files, url, this.imports.signal, root);
        if (!Object.hasOwn(captured.imports, url.href))
          throw new Error(`Source bundle is missing '${url.href}'`);
        return captured.imports[url.href];
      },
    };
  }
}
export type { DuckDBBundles };
