import { expect, test } from "./fixture";

test("marimo controls update the widget and reactive Python readback", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const analysis = page.getByRole("region", { name: "Malloy query", exact: true }).first();
  await expect(page.getByRole("heading", { name: "Sales analysis", exact: true })).toBeVisible();
  await expect(analysis.getByRole("cell", { name: "42", exact: true })).toBeVisible();
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 42}]");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(analysis.getByRole("table")).toContainText("30");
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 30}]");

  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).check();
  await expect(analysis.getByRole("alert")).toContainText("missing_source");
  await expect(page.getByText("Python received: error", { exact: false })).toBeVisible();
  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).uncheck();
  await expect(analysis.getByRole("table")).toContainText("30");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(analysis.getByRole("table")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("marimo-mobile.png"), fullPage: true });
});

test("marimo cell outputs inspect grammar and preview a bound native query", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const views = page.getByRole("region", { name: "Malloy query", exact: true });
  await expect(views).toHaveCount(4);
  const expression = views.nth(1);
  await expect(expression.getByLabel("Malloy source", { exact: true })).toHaveText("amount.sum()");
  await expression.getByText("References", { exact: true }).click();
  await expect(expression.getByLabel("Referenced fields and sources")).toHaveText("amount");
  const draft = views.nth(2);
  await expect(draft.getByRole("status")).toHaveText("Ready to inspect");
  await draft.getByRole("button", { name: "Check model", exact: true }).click();
  await expect(draft.getByRole("status")).toHaveText("Model checked");
  await draft.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(draft.getByRole("table")).toContainText("42");
  const native = views.nth(3);
  await native.getByRole("button", { name: "Check model", exact: true }).click();
  await expect(native.getByRole("status")).toHaveText("Model checked");
  await native.getByRole("button", { name: "Preview 20 rows", exact: true }).click();
  await expect(native.getByRole("table")).toContainText("9,007,199,254,740,993");
  await expect(native.getByRole("status")).toHaveText("1 row");
  await expect(native.getByText("Compiled schemas", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(views).toHaveCount(4);
  await expression.getByText("Annotations", { exact: true }).click();
  await expect(expression).toContainText("Booked amount in USD for South.");
  await page.setViewportSize({ width: 390, height: 844 });
  await native.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("notebook-inspector-mobile.png"),
    fullPage: true,
  });
});
