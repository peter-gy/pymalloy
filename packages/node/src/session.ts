import { checkSource, formatSource } from "@malloy-runtime/compiler/tooling";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { type DuckDBConnection, DuckDBInstance } from "@duckdb/node-api";
import {
  CompiledModel,
  Model,
  ToolingError,
  type ModelSource,
  type OperationOptions,
  type RunOptions,
  type SourcePosition,
} from "@malloy-runtime/compiler";
import { connection, drive, fileSearchPath, type Host } from "@malloy-runtime/duckdb";
import { DuckDBBackend } from "./duckdb";
import { Operations } from "@malloy-runtime/compiler";

export interface SessionOptions {
  dataRoot?: string;
  database?: string;
  connection?: DuckDBConnection;
}
export type ModelSpec =
  | { text: string; url?: string }
  | { path: string }
  | { url: string }
  | { source: ModelSource };
export interface CheckOptions extends OperationOptions {
  path?: string;
  syntaxOnly?: boolean;
  position?: SourcePosition;
}

export class Session {
  private readonly backend: DuckDBBackend;
  private readonly models = new Set<Model>();
  private readonly operations: Operations;
  private readonly imports = new AbortController();
  private closing?: Promise<void>;
  private constructor(
    private readonly nativeConnection: DuckDBConnection,
    private readonly dataRoot: string,
    private readonly instance?: DuckDBInstance,
  ) {
    this.operations = new Operations(() => {
      this.imports.abort();
      this.connection.interrupt();
      void this.close();
    });
    this.backend = new DuckDBBackend(nativeConnection);
  }
  static async open(options: SessionOptions = {}): Promise<Session> {
    if (options.connection && (options.database !== undefined || options.dataRoot !== undefined))
      throw new Error("Borrowed connections use the caller's database and file_search_path");
    const root = resolve(options.dataRoot ?? ".");
    if (options.connection) return new Session(options.connection, root);
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
      return new Session(native, root, instance);
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
    return {
      describe: (sql) => this.backend.describe(sql),
      readURL: async (url) => {
        this.operations.assertActive();
        if (source) {
          if (!Object.hasOwn(source.imports, url.href))
            throw new Error(`Source bundle is missing '${url.href}'`);
          return source.imports[url.href];
        }
        if (url.protocol !== "file:") throw new Error(`Import '${url}' must be a local file`);
        return readFile(url, { encoding: "utf8", signal: this.imports.signal });
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
              : pathToFileURL(resolve(this.dataRoot, "model.malloy")).href),
      );
      const host = this.host(captured);
      const compiled = await drive(
        CompiledModel.begin({
          url,
          source: captured?.text ?? ("text" in spec ? spec.text : undefined),
          connection,
        }),
        host,
      );
      this.operations.assertActive();
      const model = new Model(compiled, {
        assertActive: () => {
          this.operations.assertActive();
        },
        compile: (job) => drive(job, host),
        run: (sql, template) => this.backend.run(sql, template),
        submit: (task, options) => this.operations.run(task, options),
        release: () => this.models.delete(model),
      });
      this.models.add(model);
      return model;
    }, options);
  }
  async run(text: string, options: RunOptions = {}) {
    const captured = { signal: options.signal, givens: structuredClone(options.givens) };
    const model = await this.model({ text }, captured);
    try {
      return await model.query().run(captured);
    } finally {
      model.close();
    }
  }
  check(source: string, options: CheckOptions = {}) {
    const url = pathToFileURL(resolve(options.path ?? resolve(this.dataRoot, "inline.malloy")));
    return this.operations.run(
      () =>
        drive(
          checkSource({
            url,
            source,
            connection,
            position: options.position,
            syntaxOnly: options.syntaxOnly,
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
