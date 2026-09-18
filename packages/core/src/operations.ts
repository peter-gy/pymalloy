import type { OperationOptions } from "./types";

/** Serialize work until both the operation and its interrupt have settled. */
export class Operations {
  private pending: Promise<void> = Promise.resolve();
  private accepting = true;
  private active?: AbortController;
  private failure?: Error;

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
      let settled = false;
      const aborted = () => {
        if (settled) return;
        settled = true;
        const reason = signal?.reason ?? new DOMException("Operation was aborted", "AbortError");
        reject(reason);
        if (controller) {
          controller.abort(reason);
          interrupted = Promise.resolve().then(() => this.interrupt());
          // The queue observes this promise after the active task settles.
          void interrupted.catch(() => undefined);
        }
      };
      signal?.addEventListener("abort", aborted, { once: true });
      this.pending = this.pending.then(async () => {
        if (settled) {
          signal?.removeEventListener("abort", aborted);
          return;
        }
        controller = new AbortController();
        this.active = controller;
        try {
          this.assertActive();
          const result = await task();
          if (!settled) resolve(result);
        } catch (error) {
          if (!settled) reject(error);
        } finally {
          settled = true;
          signal?.removeEventListener("abort", aborted);
          try {
            await interrupted;
          } finally {
            this.active = undefined;
          }
        }
      });
      // A failed interrupt is terminal. Ordinary operation errors leave the queue healthy.
      this.pending = this.pending.catch((error) => {
        this.failure = error instanceof Error ? error : new Error(String(error));
        this.accepting = false;
      });
    });
  }

  close(): Promise<void> {
    this.accepting = false;
    return this.pending;
  }
}
