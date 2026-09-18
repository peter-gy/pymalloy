import { expect, test } from "./fixture.ts";

test("the base wheel runs a synchronized Malloy widget in Pyodide", async ({ page }, testInfo) => {
  const requestedAssets: string[] = [];
  page.on("request", (request) => requestedAssets.push(new URL(request.url()).pathname));
  await page.goto("/");
  await expect(page.getByLabel("Kernel status")).toHaveText("Python ready", { timeout: 120_000 });
  await expect(page.getByRole("table")).toContainText("42");
  expect(requestedAssets).toContain("/duckdb/duckdb-eh.wasm");
  expect(requestedAssets).toContain("/duckdb/duckdb-browser-eh.worker.js");
  const state = async () => JSON.parse(await page.getByLabel("Python readback").innerText());
  await expect.poll(state).toMatchObject({
    status: "ready",
    rows: [
      { region: "North", revenue: 42 },
      { region: "South", revenue: 30 },
    ],
  });
  await page.getByRole("button", { name: "Set South", exact: true }).click();
  await expect.poll(state).toMatchObject({ status: "ready", rows: [{ revenue: 30 }] });
  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("sales.by_region");
  await expect(page.getByRole("table")).toContainText("North");
  await expect.poll(state).toMatchObject({
    status: "ready",
    rows: [
      { region: "North", revenue: 42 },
      { region: "South", revenue: 30 },
    ],
  });

  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("sales.detail");
  await expect.poll(state).toMatchObject({
    status: "ready",
    rows: [
      {
        region: "North",
        values: [
          { amount: 2, subtotal: 2 },
          { amount: 40, subtotal: 40 },
        ],
      },
      { region: "South", values: [{ amount: 30, subtotal: 30 }] },
    ],
  });
  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("sales.by_region");
  await page.getByRole("button", { name: "Invalid model", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("missing_source");
  await expect.poll(state).toMatchObject({
    status: "error",
    diagnostics: [
      {
        code: "source-or-query-not-found",
        severity: "error",
        location: {
          url: expect.any(String),
          range: { start: { line: 0, character: 5 }, end: { line: 0, character: 19 } },
        },
        replacement: null,
      },
    ],
  });
  await expect(page.getByRole("alert")).toContainText("source-or-query-not-found");
  await expect(page.getByRole("alert")).toContainText(":1:6");
  await page.screenshot({ path: testInfo.outputPath("pyodide-diagnostics.png"), fullPage: true });
  await page.getByRole("button", { name: "Recover model", exact: true }).click();
  await expect.poll(state).toMatchObject({
    status: "ready",
    diagnostics: [],
    rows: [
      { region: "North", revenue: 42 },
      { region: "South", revenue: 30 },
    ],
  });
  await page.getByRole("button", { name: "Replace data", exact: true }).click();
  await expect.poll(state).toMatchObject({
    status: "ready",
    rows: [
      { region: "North", revenue: 70 },
      { region: "South", revenue: 10 },
    ],
  });
  await page.getByRole("button", { name: "Load URL data", exact: true }).click();
  await expect.poll(state).toMatchObject({
    status: "ready",
    rows: [
      { region: "North", revenue: 9 },
      { region: "South", revenue: 11 },
    ],
  });
  await page.getByRole("button", { name: "Inspect scalar types", exact: true }).click();
  const values = page.getByLabel("Python values", { exact: true });
  await expect(values).toContainText("'exact_integer': 9007199254740993");
  await expect(values).toContainText("'nested': {'value': 9007199254740993}");
  await expect(values).toContainText("'nan_value': nan");
  await expect(values).toContainText("'infinity_value': inf");
  await expect(values).toContainText("'binary_value': [0, 255]");
  await expect(page.getByRole("cell", { name: "NaN", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Infinity", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("pyodide-readback.png"), fullPage: true });
  await page.getByRole("button", { name: "Close analysis", exact: true }).click();
  await expect(page.getByLabel("Kernel status")).toHaveText("Analysis closed");
  await expect.poll(state).toMatchObject({ status: "closed", rows: [] });
  await expect(page.getByRole("table")).toHaveCount(0);
});
