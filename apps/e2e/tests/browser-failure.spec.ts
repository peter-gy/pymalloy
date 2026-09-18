import { expect, test } from "@playwright/test";
test("a worker exception settles queued work and closes its session", async ({ page }) => {
  await page.route("**/failing-worker.js", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `importScripts(${JSON.stringify(new URL("/duckdb/duckdb-browser-mvp.worker.js", route.request().url()).href)});
      self.addEventListener("message", (event) => {
        if (JSON.stringify(event.data).includes("browser_failure")) {
          throw new Error("Deliberate browser acceptance worker failure");
        }
      });`,
    }),
  );
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const session = await Session.open({
      bundles: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/failing-worker.js", location.href).href,
        },
      },
    });
    const failed = session.run(
      "run: duckdb.sql('SELECT 42 AS browser_failure') -> { select: browser_failure }",
    );
    const queued = session.run("run: duckdb.sql('SELECT 99 AS value') -> { select: value }");
    const outcomes = await Promise.allSettled([failed, queued]);
    await session.close();
    return { closed: session.closed, outcomes: outcomes.map((outcome) => outcome.status) };
  });
  expect(output).toEqual({ closed: true, outcomes: ["rejected", "rejected"] });
});
