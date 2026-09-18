import type { FieldDef } from "@malloydata/malloy";

/** @title SchemaNeed */
export interface SchemaNeed {
  key: string;
  connection: string;
  sql: string;
  tablePath?: string;
}
/** @title Needs */
export interface Needs {
  urls: string[];
  schemas: SchemaNeed[];
}
type Answer<T> = { value: T } | { error: string };
/** @title Fulfilled */
export interface Fulfilled {
  urls: Record<string, Answer<string>>;
  schemas: Record<string, Answer<FieldDef[]>>;
}
export type Task<T> = Generator<Needs, T, Fulfilled>;
export type Step<T> = { needs: Needs } | { result: T };

export class Job<T> {
  private complete = false;
  constructor(private readonly task: Task<T>) {}
  step(fulfilled?: Fulfilled): Step<T> {
    if (this.complete) throw new Error("Compiler job is complete");
    const step = fulfilled === undefined ? this.task.next() : this.task.next(fulfilled);
    if (step.done) {
      this.complete = true;
      return { result: step.value };
    }
    return { needs: step.value };
  }
  close(): void {
    this.complete = true;
    // SAFETY: Closing discards the return value and executes generator cleanup.
    this.task.return(undefined as never);
  }
}
