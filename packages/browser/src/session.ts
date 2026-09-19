import { Table } from "apache-arrow";
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
  documentKind,
  type DocumentKind,
  Model,
  Operations,
  ToolingError,
  type OperationOptions,
  type QueryOptions,
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
import { type File, type Files, modelURL, snapshot, readImport } from "./files";

export interface SessionOptions {
  bundles?: DuckDBBundles;
  signal?: AbortSignal;
  connectionName?: string;
}
export type ModelSpec = (
  | { text: string; url?: string }
  | { source: ModelSource }
  | { url: string }
) & { files?: Files; documentKind?: DocumentKind };
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
    private readonly connectionName: string,
  ) {
    this.operations = new Operations(async () => {
      try {
        await this.connection.cancelSent();
      } catch (error) {
        this.fail(error instanceof Error ? error : new Error(String(error)));
        throw error;
      }
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
        options.connectionName ?? compilerConnection.name,
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
          connection: { ...compilerConnection, name: this.connectionName },
          documentKind: spec.documentKind ?? captured?.documentKind ?? documentKind(root),
        }),
        host,
      );
      if (this.stopped) throw new Error("Session is closed");
      this.operations.assertActive();
      const schemas = new Map<string, { signature: string; columns: Column[] }>();
      const model = new Model(compiled, {
        assertAvailable: () => {
          if (this.stopped) throw new Error("Session is closed");
          this.operations.assertHealthy();
        },
        compile: (job) => drive(job, this.host(files, root, captured)),
        run: async (sql, template) => {
          const host = this.host(files, root, captured);
          const cached = schemas.get(sql);
          let columns = cached?.columns ?? (await host.describe(`DESCRIBE ${sql}`));
          const table = await this.query(sql);
          const data = materialize(table);
          const signature = JSON.stringify(table.schema, (_key, value) =>
            value instanceof Map ? [...value] : value,
          );
          const reusable =
            table.schema.dictionaries.size === 0 && sql.length + signature.length <= 65_536;
          if (cached && (!reusable || cached.signature !== signature)) {
            columns = await host.describe(`DESCRIBE ${sql}`);
          }
          if (reusable && cached?.signature !== signature) {
            if (schemas.size === 32) schemas.delete(schemas.keys().next().value!);
            schemas.set(sql, { signature, columns });
          }
          return {
            sql,
            rows: data.rows,
            columns: structuredClone(columns),
            malloy: stableResult(sql, columns, data.rows, template, this.connectionName),
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
  async run(text: string, options: QueryOptions & { files?: Files } = {}) {
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
      documentKind?: DocumentKind;
      position?: SourcePosition;
    } & OperationOptions = {},
  ) {
    const { signal, files: inputFiles, ...input } = options;
    const files = snapshot(inputFiles);
    const captured = structuredClone(input);
    const root = new URL(captured.url ?? modelURL);
    return this.enqueue(
      async () => {
        await this.activate(files);
        return drive(
          checkSource({
            url: root,
            source: text,
            connection: { ...compilerConnection, name: this.connectionName },
            syntaxOnly: captured.syntaxOnly,
            documentKind: captured.documentKind ?? documentKind(root),
            position: captured.position,
          }),
          this.host(files, root),
        );
      },
      { signal },
    );
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
    return this.operations.run(() => {
      if (this.stopped) throw new Error("Session is closed");
      return Promise.race([task(), this.failure]);
    }, options);
  }

  private async query(sql: string): Promise<Table> {
    const active = this.operations.signal;
    const signal = active ? AbortSignal.any([active, this.imports.signal]) : this.imports.signal;
    signal.throwIfAborted();
    const reader = await this.connection.send(sql, false);
    signal.throwIfAborted();
    const batches = await reader.readAll();
    signal.throwIfAborted();
    return new Table(reader.schema, batches);
  }

  private async activate(files: Map<string, File>): Promise<void> {
    this.operations.assertActive();
    if (this.activeSnapshot === files) return;
    this.activeSnapshot = undefined;
    for (const name of this.activeFiles) await this.database.dropFile(name);
    this.activeFiles = [];
    for (const [name, file] of files) {
      this.operations.assertActive();
      if (file instanceof Uint8Array) await this.database.registerFileBuffer(name, file.slice());
      else await this.database.registerFileURL(name, file.url, DuckDBDataProtocol.HTTP, true);
      this.activeFiles.push(name);
    }
    this.activeSnapshot = files;
  }

  private host(files: Map<string, File>, root: URL, captured?: ModelSource): Host {
    const operations = this.operations;
    const signal = operations.signal
      ? AbortSignal.any([operations.signal, this.imports.signal])
      : this.imports.signal;
    return {
      signal,
      describe: async (sql) => {
        signal.throwIfAborted();
        const statement = await this.connection.prepare(sql);
        await statement.close();
        const result = await this.query(sql);
        return result
          .toArray()
          .map((row) => ({ name: String(row.column_name), type: String(row.column_type) }));
      },
      readURL: async (url) => {
        if (!captured) return readImport(files, url, signal, root);
        if (!Object.hasOwn(captured.imports, url.href))
          throw new Error(`Source bundle is missing '${url.href}'`);
        return captured.imports[url.href];
      },
    };
  }
}
export type { DuckDBBundles };
