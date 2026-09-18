export interface OperationOptions {
  timeout?: number;
  signal?: AbortSignal;
}

export function operationTimeout(value: number): number {
  if (!Number.isFinite(value) || value <= 0 || value > 2_147_483_647) {
    throw new RangeError("timeout must be positive milliseconds within the timer range");
  }
  return value;
}

export class Operations {
  private pending: Promise<void> = Promise.resolve();
  private accepting = true;
  private failure?: Error;
  private readonly cancellations = new Set<(error: Error) => void>();

  constructor(
    private readonly timeout: number,
    private readonly interrupt: () => void,
  ) {}

  get closed(): boolean {
    return !this.accepting;
  }

  assertActive(): void {
    if (this.failure) throw this.failure;
  }

  run<T>(task: () => Promise<T>, options: OperationOptions = {}): Promise<T> {
    if (!this.accepting) return Promise.reject(new Error("Session is closed"));
    let timeout: number;
    try {
      timeout = operationTimeout(options.timeout ?? this.timeout);
      options.signal?.throwIfAborted();
    } catch (error) {
      return Promise.reject(error);
    }
    const signal = options.signal;
    const deadline = performance.now() + timeout;
    return new Promise<T>((resolve, reject) => {
      let active = false;
      let settled = false;
      const cleanup = () => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", aborted);
        this.cancellations.delete(cancel);
      };
      const cancel = (error: Error) => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(error);
        if (active) this.stop(error);
      };
      const aborted = () =>
        cancel(
          signal?.reason instanceof Error
            ? signal.reason
            : new DOMException("Operation was aborted", "AbortError"),
        );
      const expired = () =>
        cancel(new DOMException(`Operation exceeded ${timeout} ms`, "TimeoutError"));
      const timer = setTimeout(expired, timeout);
      this.cancellations.add(cancel);
      signal?.addEventListener("abort", aborted, { once: true });
      this.pending = this.pending.then(async () => {
        if (settled) return;
        if (performance.now() >= deadline) {
          expired();
          return;
        }
        active = true;
        try {
          this.assertActive();
          const result = await task();
          if (!settled && performance.now() >= deadline) expired();
          else if (!settled) resolve(result);
        } catch (error) {
          if (!settled) reject(error);
        } finally {
          active = false;
          settled = true;
          cleanup();
        }
      });
    });
  }

  private stop(error: Error): void {
    if (this.failure) return;
    this.failure = error;
    this.accepting = false;
    this.interrupt();
    for (const cancel of this.cancellations) cancel(error);
  }

  close(): Promise<void> {
    this.accepting = false;
    return this.pending;
  }
}
