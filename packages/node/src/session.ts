import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { type DuckDBConnection, DuckDBInstance, type JS } from "@duckdb/node-api";
import {
  CompiledModel,
  checkSource,
  formatSource,
  ToolingError,
  type CheckReport,
  type GivenValue,
  type Inspection,
  type LoadOptions,
  type Position,
  type ReferenceInfo,
} from "@pymalloy/core";
import { DuckDBBackend } from "./duckdb.js";
import { Operations, operationTimeout, type OperationOptions } from "./operations.js";

export type Row = Record<string, JS>;

function querySource(value: string | RunOptions): value is string {
  return typeof value === "string";
}

export interface SessionOptions {
  dataRoot?: string;
  database?: string;
  connection?: DuckDBConnection;
  timeout?: number;
}

export interface RunOptions extends OperationOptions {
  query?: string;
  givens?: Record<string, GivenValue>;
}

export interface CheckOptions extends OperationOptions {
  path?: string;
  syntaxOnly?: boolean;
  position?: Position;
}

export interface InspectOptions {
  position?: Position;
  url?: URL;
}

export class Session {
  private readonly backend: DuckDBBackend;
  private readonly models = new Set<SessionModel>();
  private readonly operations: Operations;
  private readonly imports = new AbortController();
  private closing?: Promise<void>;

  private constructor(
    private readonly nativeConnection: DuckDBConnection,
    private readonly dataRoot: string | undefined,
    timeout: number,
    private readonly instance?: DuckDBInstance,
  ) {
    this.operations = new Operations(timeout, () => {
      this.imports.abort();
      try {
        this.nativeConnection.interrupt();
      } finally {
        void this.close();
      }
    });
    this.backend = new DuckDBBackend(nativeConnection, () => this.operations.assertActive());
  }

  static async create(options: SessionOptions = {}): Promise<Session> {
    if (options.connection && options.database !== undefined)
      throw new Error("Choose connection or database");
    const timeout = operationTimeout(options.timeout ?? 120_000);
    const dataRoot = options.dataRoot === undefined ? undefined : resolve(options.dataRoot);
    if (options.connection) return new Session(options.connection, dataRoot, timeout);
    const instance = await DuckDBInstance.create(options.database);
    try {
      const connection = await instance.connect();
      try {
        await connection.run("SET TimeZone = 'UTC'");
      } catch (error) {
        connection.closeSync();
        throw error;
      }
      return new Session(connection, dataRoot, timeout, instance);
    } catch (error) {
      instance.closeSync();
      throw error;
    }
  }

  get connection(): DuckDBConnection {
    return this.nativeConnection;
  }

  get closed(): boolean {
    return this.operations.closed;
  }

  model(source: string, options: OperationOptions & { baseDir?: string } = {}): Promise<Model> {
    const baseDir = resolve(options.baseDir ?? this.dataRoot ?? ".");
    return this.operations.run(
      () => this.loadModel(pathToFileURL(resolve(baseDir, "model.malloy")), source, baseDir),
      options,
    );
  }

  load(path: string, options: OperationOptions = {}): Promise<Model> {
    const url = pathToFileURL(resolve(path));
    const baseDir = resolve(path, "..");
    return this.operations.run(() => this.loadModel(url, undefined, baseDir), options);
  }

  run(source: string, options: RunOptions = {}): Promise<Row[]> {
    const selected = structuredClone({ query: options.query, givens: options.givens });
    const baseDir = this.dataRoot ?? resolve(".");
    return this.operations.run(async () => {
      const compiled = await CompiledModel.load(
        this.loadOptions(pathToFileURL(resolve(baseDir, "model.malloy")), source, baseDir),
      );
      const query = await compiled.query(selected.query, undefined, selected.givens);
      return this.backend.run(query.sql, baseDir);
    }, options);
  }

  check(source: string, options: CheckOptions = {}): Promise<CheckReport> {
    return this.checkRequest(source, options);
  }

  checkFile(path: string, options: Omit<CheckOptions, "path"> = {}): Promise<CheckReport> {
    return this.checkRequest(undefined, { ...options, path: resolve(path) });
  }

  private checkRequest(source: string | undefined, options: CheckOptions): Promise<CheckReport> {
    const path = resolve(options.path ?? resolve(this.dataRoot ?? ".", "inline.malloy"));
    const url = pathToFileURL(path);
    const position = options.position && { ...options.position };
    const syntaxOnly = options.syntaxOnly ?? false;
    const load = this.loadOptions(url, source, resolve(path, ".."));
    return this.operations.run(() => checkSource({ ...load, position, syntaxOnly }), options);
  }

  format(source: string, options: OperationOptions = {}): Promise<string> {
    return this.operations.run(async () => {
      const result = formatSource(source);
      if (result.diagnostics.some((diagnostic) => diagnostic.severity === "error")) {
        throw new ToolingError(
          result.diagnostics.map((diagnostic) => diagnostic.message).join("\n"),
          result.diagnostics,
        );
      }
      return result.source;
    }, options);
  }

  close(): Promise<void> {
    if (!this.closing) {
      this.closing = this.operations.close().then(() => {
        for (const model of this.models) model.close();
        this.imports.abort();
        if (this.instance) {
          this.nativeConnection.closeSync();
          this.instance.closeSync();
        }
      });
    }
    return this.closing;
  }

  private loadOptions(url: URL, source: string | undefined, baseDir: string): LoadOptions {
    return {
      url,
      source,
      describe: (sql) => this.backend.describe(sql, this.dataRoot ?? baseDir),
      readURL: async (importURL) => {
        this.operations.assertActive();
        if (importURL.protocol !== "file:")
          throw new Error(`Import '${importURL}' must be a local file`);
        return readFile(importURL, { encoding: "utf8", signal: this.imports.signal });
      },
    };
  }

  private async loadModel(url: URL, source: string | undefined, baseDir: string): Promise<Model> {
    const root = this.dataRoot ?? baseDir;
    const compiled = await CompiledModel.load(this.loadOptions(url, source, baseDir));
    this.operations.assertActive();
    const model = new SessionModel(
      compiled,
      this.operations,
      {
        sql: (sql) => this.backend.bind(sql, root, true),
        run: (sql) => this.backend.run(sql, root),
      },
      () => this.models.delete(model),
    );
    this.models.add(model);
    return model;
  }
}

export interface Model {
  readonly queries: readonly string[];
  inspect(options?: InspectOptions): Inspection & Partial<ReferenceInfo>;
  sql(options?: RunOptions): Promise<string>;
  sql(source: string, options?: RunOptions): Promise<string>;
  run(options?: RunOptions): Promise<Row[]>;
  run(source: string, options?: RunOptions): Promise<Row[]>;
  close(): void;
}

class SessionModel implements Model {
  readonly queries: readonly string[];
  private compiled: CompiledModel | undefined;

  constructor(
    compiled: CompiledModel,
    private operations: Operations | undefined,
    private data:
      | {
          sql: (sql: string) => Promise<string>;
          run: (sql: string) => Promise<Row[]>;
        }
      | undefined,
    private release: (() => void) | undefined,
  ) {
    this.compiled = compiled;
    this.queries = compiled.queries;
  }

  inspect(options: InspectOptions = {}): Inspection & Partial<ReferenceInfo> {
    const compiled = this.current();
    if (options.url && !options.position) throw new Error("url requires a position");
    const inspection = compiled.inspect();
    if (!options.position) return inspection;
    return { ...inspection, ...compiled.reference({ ...options.position, url: options.url }) };
  }

  sql(options?: RunOptions): Promise<string>;
  sql(source: string, options?: RunOptions): Promise<string>;
  sql(sourceOrOptions: string | RunOptions = {}, options: RunOptions = {}): Promise<string> {
    return this.submit(sourceOrOptions, options, this.data?.sql);
  }

  run(options?: RunOptions): Promise<Row[]>;
  run(source: string, options?: RunOptions): Promise<Row[]>;
  run(sourceOrOptions: string | RunOptions = {}, options: RunOptions = {}): Promise<Row[]> {
    return this.submit(sourceOrOptions, options, this.data?.run);
  }

  close(): void {
    this.compiled = undefined;
    this.operations = undefined;
    this.data = undefined;
    this.release?.();
    this.release = undefined;
  }

  private current(): CompiledModel {
    if (!this.compiled || !this.operations) throw new Error("Model is closed");
    this.operations.assertActive();
    return this.compiled;
  }

  private submit<T>(
    sourceOrOptions: string | RunOptions,
    options: RunOptions,
    execute: ((sql: string) => Promise<T>) | undefined,
  ): Promise<T> {
    if (!this.operations) return Promise.reject(new Error("Model is closed"));
    if (this.operations.closed) return Promise.reject(new Error("Session is closed"));
    if (!execute) return Promise.reject(new Error("Model is closed"));
    const source = querySource(sourceOrOptions) ? sourceOrOptions : undefined;
    const selected = querySource(sourceOrOptions) ? options : sourceOrOptions;
    const { query, givens } = structuredClone({ query: selected.query, givens: selected.givens });
    return this.operations.run(async () => {
      const compiled = this.current();
      if (source !== undefined && query !== undefined) throw new Error("Choose source or query");
      const prepared = await compiled.query(query, source, givens);
      return execute(prepared.sql);
    }, selected);
  }
}

export type { OperationOptions };
