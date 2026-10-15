import { isMalloyText, selectQuery } from "./selection";
import { drive, type Host } from "./drive";
import type { OperationOptions } from "./types";
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

interface ModelDriver {
  assertAvailable(): void;
  compile<T>(job: Job<T>): Promise<T>;
  run(sql: string, malloy?: Result["malloy"]): Promise<Result>;
  submit<T>(task: () => Promise<T>, options?: QueryOptions): Promise<T>;
  release(): void;
}

export class Model {
  readonly queries: readonly Readonly<QueryDescriptor>[];
  private compiled?: CompiledModel;
  private driver?: ModelDriver;
  private constructor(compiled: CompiledModel, driver: ModelDriver) {
    this.compiled = compiled;
    this.driver = driver;
    this.queries = compiled.queries;
  }
  static create(compiled: CompiledModel, driver: ModelDriver): Model {
    return new Model(compiled, driver);
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
    return Query.create(
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
  readonly schema: QueryDescriptor["schema"];
  private constructor(
    info: QueryDescriptor,
    private readonly compile: (options: QueryOptions) => Promise<string>,
    private readonly execute: (options: QueryOptions) => Promise<Result>,
  ) {
    this.name = info.name;
    this.kind = info.kind;
    this.location = info.location;
    this.schema = info.schema;
  }
  static create(
    info: QueryDescriptor,
    compile: (options: QueryOptions) => Promise<string>,
    execute: (options: QueryOptions) => Promise<Result>,
  ): Query {
    return new Query(info, compile, execute);
  }
  async sql(options: QueryOptions = {}): Promise<string> {
    return this.compile(options);
  }
  async run(options: QueryOptions = {}): Promise<Result> {
    return this.execute(options);
  }
}

interface Execution {
  host(): Host;
  run(sql: string, malloy?: Result["malloy"]): Promise<Result>;
  submit<T>(task: () => Promise<T>, options?: QueryOptions): Promise<T>;
  assertAvailable(): void;
  release(): void;
}

export class Runtime {
  private pending: Promise<void> = Promise.resolve();
  private accepting = true;
  private active?: AbortController;
  private failure?: Error;
  private abortActive?: () => void;

  private readonly models = new Set<Model>();
  constructor(private readonly interrupt: () => void | Promise<void>) {}

  get closed(): boolean {
    return !this.accepting;
  }

  get signal(): AbortSignal | undefined {
    return this.active?.signal;
  }

  assertHealthy(): void {
    if (this.failure) throw this.failure;
  }

  assertActive(): void {
    this.assertHealthy();
    this.active?.signal.throwIfAborted();
  }

  run<T>(task: () => Promise<T>, options: OperationOptions = {}): Promise<T> {
    if (!this.accepting) return Promise.reject(new Error("Session is closed"));
    try {
      options.signal?.throwIfAborted();
    } catch (error) {
      return Promise.reject(error);
    }
    const signal = options.signal;
    return new Promise<T>((resolve, reject) => {
      let controller: AbortController | undefined;
      let interrupted: Promise<void> | undefined;
      let abortReason: unknown;
      let settled = false;
      const aborted = () => {
        if (settled) return;
        const reason =
          signal?.reason ??
          controller?.signal.reason ??
          new DOMException("Operation was aborted", "AbortError");
        if (!controller) {
          settled = true;
          reject(reason);
          return;
        }
        if (interrupted) return;
        abortReason = reason;
        controller.abort(reason);
        try {
          interrupted = Promise.resolve(this.interrupt());
        } catch (error) {
          interrupted = Promise.reject(error);
        }
        // The active operation observes interruption before publishing its outcome.
        void interrupted.catch(() => undefined);
      };
      signal?.addEventListener("abort", aborted, { once: true });
      this.pending = this.pending.then(async () => {
        if (settled) {
          signal?.removeEventListener("abort", aborted);
          return;
        }
        controller = new AbortController();
        this.active = controller;
        this.abortActive = aborted;
        let outcome: { value: T } | { error: unknown };
        try {
          this.assertActive();
          outcome = { value: await task() };
        } catch (error) {
          outcome = { error };
        } finally {
          settled = true;
          signal?.removeEventListener("abort", aborted);
          try {
            await interrupted;
          } catch (error) {
            this.failure = error instanceof Error ? error : new Error(String(error));
            this.accepting = false;
          } finally {
            this.active = undefined;
            this.abortActive = undefined;
          }
        }
        if ("value" in outcome) resolve(outcome.value);
        else reject(this.failure ?? (interrupted ? abortReason : outcome.error));
      });
      // A failed interrupt is terminal. Ordinary operation errors leave the queue healthy.
      this.pending = this.pending.catch((error) => {
        this.failure = error instanceof Error ? error : new Error(String(error));
        this.accepting = false;
      });
    });
  }

  close(abort = false): Promise<void> {
    this.accepting = false;
    if (abort) {
      this.active?.abort(new DOMException("Session is closed", "AbortError"));
      this.abortActive?.();
    }
    return this.pending.then(() => this.assertHealthy());
  }
  model(compiled: CompiledModel, execution: Execution): Model {
    const model = Model.create(compiled, {
      assertAvailable: () => {
        execution.assertAvailable();
        this.assertHealthy();
      },
      compile: (job) => drive(job, execution.host()),
      run: (sql, template) => {
        this.assertActive();
        return execution.run(sql, template);
      },
      submit: (task, options) => execution.submit(task, options),
      release: () => {
        this.models.delete(model);
        execution.release();
      },
    });
    this.models.add(model);
    return model;
  }
  release(): void {
    for (const model of this.models) model.close();
  }
}
