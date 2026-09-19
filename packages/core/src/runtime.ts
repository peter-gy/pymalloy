import { isMalloyText, selectQuery } from "./selection";
import type { CompiledModel } from "./model";
import type { Job } from "./job";
import type { SourcePosition } from "./metadata";
import type {
  QueryDescriptor,
  QuerySelection,
  QueryOptions,
  DocumentOptions,
  Result,
} from "./types";

interface InspectOptions {
  position?: SourcePosition;
  url?: URL;
}
type Prepared = ReturnType<CompiledModel["prepare"]> extends Job<infer T> ? T : never;

/** @title ModelDriver */
export interface ModelDriver {
  assertAvailable(): void;
  compile<T>(job: Job<T>): Promise<T>;
  run(sql: string, malloy?: Result["malloy"]): Promise<Result>;
  submit<T>(task: () => Promise<T>, options?: QueryOptions): Promise<T>;
  release(): void;
}

export class Model {
  readonly queries: readonly Readonly<QueryDescriptor>[];
  constructor(
    private compiled: CompiledModel | undefined,
    private driver: ModelDriver | undefined,
  ) {
    this.queries = compiled!.queries;
  }
  private current() {
    if (!this.compiled || !this.driver) throw new Error("Model is closed");
    this.driver.assertAvailable();
    return { compiled: this.compiled, driver: this.driver };
  }
  source() {
    return this.current().compiled.source();
  }
  inspect(options: InspectOptions = {}) {
    const { compiled } = this.current();
    if (options.url && !options.position) throw new Error("url requires a position");
    const inspection = compiled.inspect();
    return options.position
      ? { ...inspection, ...compiled.reference({ ...options.position, url: options.url }) }
      : inspection;
  }
  query(selection?: QuerySelection): Query {
    this.current();
    let info: QueryDescriptor;
    if (isMalloyText(selection)) info = { name: "query", kind: "run", location: null };
    else {
      info = selectQuery(this.queries, selection);
      selection = info.name;
    }
    const selected = structuredClone(selection);
    const execute = <T>(
      options: QueryOptions,
      finish: (prepared: Prepared, driver: ModelDriver) => T | Promise<T>,
    ) => {
      const { driver } = this.current();
      const values = structuredClone(options.givens);
      return driver.submit(async () => {
        const { compiled } = this.current();
        const prepared = await driver.compile(compiled.prepare(selected, { givens: values }));
        return finish(prepared, driver);
      }, options);
    };
    return new Query(
      info,
      (options) => execute(options, (prepared) => prepared.sql),
      (options) =>
        execute(options, (prepared, driver) => driver.run(prepared.sql, prepared.malloy)),
    );
  }
  document(options: DocumentOptions = {}) {
    const { driver } = this.current();
    const { signal, ...document } = options;
    const captured = structuredClone(document);
    return driver.submit(() => driver.compile(this.current().compiled.document(captured)), {
      signal,
    });
  }
  close(): void {
    this.compiled = undefined;
    this.driver?.release();
    this.driver = undefined;
  }
}

export class Query implements QueryDescriptor {
  readonly name: string;
  readonly kind: QueryDescriptor["kind"];
  readonly location: QueryDescriptor["location"];
  constructor(
    info: QueryDescriptor,
    private readonly compile: (options: QueryOptions) => Promise<string>,
    private readonly execute: (options: QueryOptions) => Promise<Result>,
  ) {
    this.name = info.name;
    this.kind = info.kind;
    this.location = info.location;
  }
  async sql(options: QueryOptions = {}): Promise<string> {
    return this.compile(options);
  }
  async run(options: QueryOptions = {}): Promise<Result> {
    return this.execute(options);
  }
}
