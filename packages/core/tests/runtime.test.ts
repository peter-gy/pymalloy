import { expect, test } from "vite-plus/test";
import { Runtime } from "../src/runtime";

test("active cancellation waits for the interrupt before rejecting its caller", async () => {
  const started = Promise.withResolvers<void>();
  const task = Promise.withResolvers<never>();
  const interrupt = Promise.withResolvers<void>();
  const controller = new AbortController();
  const events: string[] = [];
  const runtime = new Runtime(async () => {
    events.push("interrupt started");
    task.reject(new Error("engine interrupted"));
    await interrupt.promise;
    events.push("interrupt finished");
  });
  const running = runtime
    .run(
      () => {
        started.resolve();
        return task.promise;
      },
      { signal: controller.signal },
    )
    .catch((error) => {
      events.push("caller rejected");
      throw error;
    });
  const outcome = expect(running).rejects.toMatchObject({ name: "AbortError" });
  await started.promise;
  controller.abort();
  expect(events).toEqual(["interrupt started"]);
  const queued = runtime.run(async () => {
    events.push("next task");
    return 99;
  });
  interrupt.resolve();
  await outcome;
  expect(await queued).toBe(99);
  expect(events).toEqual([
    "interrupt started",
    "interrupt finished",
    "caller rejected",
    "next task",
  ]);
  await runtime.close();
});

test("close retains a completed task value while awaiting interruption", async () => {
  const interrupt = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const runtime = new Runtime(() => interrupt.promise);
  let closing: Promise<void> | undefined;
  const running = runtime.run(async () => {
    closing = runtime.close(true);
    started.resolve();
    return 42;
  });
  await started.promise;
  interrupt.resolve();
  expect(await running).toBe(42);
  await closing;
});

test("a produced value survives a failing close interruption", async () => {
  const interrupt = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const runtime = new Runtime(() => interrupt.promise);
  let closing: Promise<void> | undefined;
  const running = runtime.run(async () => {
    closing = runtime.close(true);
    started.resolve();
    return 42;
  });
  await started.promise;
  const closed = expect(closing).rejects.toThrow("interrupt failed");
  interrupt.reject(new Error("interrupt failed"));
  expect(await running).toBe(42);
  await closed;
});

test("an asynchronous interrupt failure rejects close and queued work", async () => {
  const started = Promise.withResolvers<void>();
  const task = Promise.withResolvers<never>();
  const interrupt = Promise.withResolvers<void>();
  const runtime = new Runtime(() => {
    task.reject(new Error("engine interrupted"));
    return interrupt.promise;
  });
  const running = runtime.run(() => {
    started.resolve();
    return task.promise;
  });
  const runningOutcome = expect(running).rejects.toThrow("interrupt failed");
  await started.promise;
  let invoked = false;
  const queued = runtime.run(async () => {
    invoked = true;
  });
  const queuedOutcome = expect(queued).rejects.toThrow("interrupt failed");
  const closing = expect(runtime.close(true)).rejects.toThrow("interrupt failed");
  interrupt.reject(new Error("interrupt failed"));
  await Promise.all([runningOutcome, queuedOutcome, closing]);
  expect(invoked).toBe(false);
  expect(() => runtime.assertHealthy()).toThrow("interrupt failed");
});
