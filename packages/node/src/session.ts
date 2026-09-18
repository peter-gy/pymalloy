import { checkSource, formatSource } from "@malloy-runtime/compiler/tooling";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { type DuckDBConnection, DuckDBInstance } from "@duckdb/node-api";
import {
  CompiledModel,
  documentKind,
  defaultSourceFilename,
  type DocumentKind,
  Model,
  ToolingError,
  type ModelSource,
  type OperationOptions,
  type QueryOptions,
  type SourcePosition,
} from "@malloy-runtime/compiler";
import { connection, drive, fileSearchPath, type Host } from "@malloy-runtime/duckdb";
import { DuckDBBackend } from "./duckdb";
import { Operations } from "@malloy-runtime/compiler";

export interface SessionOptions {
  dataRoot?: string;
  database?: string;
  connection?: DuckDBConnection;
  connectionName?: string;
}
export type ModelSpec = (
  | { text: string; url?: string }
  | { path: string }
  | { url: string }
  | { source: ModelSource }
) & { documentKind?: DocumentKind };
export interface CheckOptions extends OperationOptions {
  path?: string;
  syntaxOnly?: boolean;
  documentKind?: DocumentKind;
  position?: SourcePosition;
}

export class Session {
  private readonly backend: DuckDBBackend;
  private readonly compilerConnection: typeof connection;
  private readonly models = new Set<Model>();
  private readonly operations: Operations;
  private readonly imports = new AbortController();
  private closing?: Promise<void>;
  private constructor(
    private readonly nativeConnection: DuckDBConnection,
    private readonly dataRoot: string,
    private readonly instance?: DuckDBInstance,
    connectionName = connection.name,
  ) {
    this.operations = new Operations(() => this.connection.interrupt());
    this.compilerConnection = { ...connection, name: connectionName };
    this.backend = new DuckDBBackend(nativeConnection, connectionName);
  }
  static async open(options: SessionOptions = {}): Promise<Session> {
    if (options.connection && (options.database !== undefined || options.dataRoot !== undefined))
      throw new Error("Borrowed connections use the caller's database and file_search_path");
    const root = resolve(options.dataRoot ?? ".");
    if (options.connection)
      return new Session(options.connection, root, undefined, options.connectionName);
    const instance = await DuckDBInstance.create(options.database);
    try {
      const native = await instance.connect();
      try {
        await native.run("SET TimeZone='UTC'");
        await native.run(fileSearchPath(root));
      } catch (error) {
        native.closeSync();
        throw error;
      }
      return new Session(native, root, instance, options.connectionName);
    } catch (error) {
      instance.closeSync();
      throw error;
    }
  }
  get connection(): DuckDBConnection {
    return this.nativeConnection;
  }
  get closed() {
    return this.operations.closed;
  }
  private host(source?: ModelSource): Host {
    const operations = this.operations;
    const signal = operations.signal
      ? AbortSignal.any([operations.signal, this.imports.signal])
      : this.imports.signal;
    return {
      signal,
      describe: (sql) => {
        signal.throwIfAborted();
        return this.backend.describe(sql);
      },
      readURL: async (url) => {
        signal.throwIfAborted();
        if (source) {
          if (!Object.hasOwn(source.imports, url.href))
            throw new Error(`Source bundle is missing '${url.href}'`);
          return source.imports[url.href];
        }
        if (url.protocol !== "file:") throw new Error(`Import '${url}' must be a local file`);
        return readFile(url, {
          encoding: "utf8",
          signal,
        });
      },
    };
  }
  model(input: ModelSpec, options: OperationOptions = {}): Promise<Model> {
    const spec = structuredClone(input);
    if ("path" in spec) spec.path = resolve(spec.path);
    return this.operations.run(async () => {
      const captured = "source" in spec ? spec.source : undefined;
      const url = new URL(
        captured?.url ??
          ("path" in spec
            ? pathToFileURL(resolve(spec.path)).href
            : "url" in spec && spec.url
              ? spec.url
              : pathToFileURL(resolve(this.dataRoot, defaultSourceFilename)).href),
      );
      const host = this.host(captured);
      const compiled = await drive(
        CompiledModel.begin({
          url,
          source: captured?.text ?? ("text" in spec ? spec.text : undefined),
          connection: this.compilerConnection,
          documentKind: spec.documentKind ?? captured?.documentKind ?? documentKind(url),
        }),
        host,
      );
      this.operations.assertActive();
      const model = new Model(compiled, {
        assertAvailable: () => this.operations.assertHealthy(),
        compile: (job) => drive(job, this.host(captured)),
        run: (sql, template) => {
          this.operations.assertActive();
          return this.backend.run(sql, template, this.operations.signal);
        },
        submit: (task, options) => this.operations.run(task, options),
        release: () => this.models.delete(model),
      });
      this.models.add(model);
      return model;
    }, options);
  }
  async run(text: string, options: QueryOptions = {}) {
    const captured = { signal: options.signal, givens: structuredClone(options.givens) };
    const model = await this.model({ text }, captured);
    try {
      return await model.query().run(captured);
    } finally {
      model.close();
    }
  }
  check(source: string, options: CheckOptions = {}) {
    const url = pathToFileURL(
      resolve(options.path ?? resolve(this.dataRoot, defaultSourceFilename)),
    );
    return this.operations.run(
      () =>
        drive(
          checkSource({
            url,
            source,
            connection: this.compilerConnection,
            position: options.position,
            syntaxOnly: options.syntaxOnly,
            documentKind: options.documentKind ?? documentKind(url),
          }),
          this.host(),
        ),
      options,
    );
  }
  format(source: string) {
    const result = formatSource(source);
    if (result.diagnostics.length)
      throw new ToolingError("Malloy formatting failed", result.diagnostics);
    return result.source;
  }
  close(): Promise<void> {
    this.closing ??= this.operations.close().then(() => {
      for (const model of this.models) model.close();
      this.imports.abort();
      if (this.instance) {
        this.connection.closeSync();
        this.instance.closeSync();
      }
    });
    return this.closing;
  }
}
