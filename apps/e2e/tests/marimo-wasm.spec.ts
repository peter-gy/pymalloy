import { expect, test } from "./fixture";

test("marimo WebAssembly synchronizes a widget with browser Python", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await expect(
    page.getByRole("table").or(page.getByText("An internal error occurred", { exact: true })),
  ).toBeVisible({ timeout: 180_000 });
  if (await page.getByText("An internal error occurred", { exact: true }).isVisible())
    throw new Error("The marimo WebAssembly notebook failed during execution");
  await expect(page.getByRole("table")).toContainText("42", { timeout: 180_000 });
  await expect(page.getByText("Rows: [{'revenue': 42}]", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(page.getByRole("table")).toContainText("30");
  await expect(page.getByText("Rows: [{'revenue': 30}]", { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("marimo-wasm-widget.png"), fullPage: true });
  await page.getByRole("checkbox", { name: "Close analysis", exact: true }).check();
  await expect(page.getByRole("table")).toHaveCount(0);
  await expect(page.getByText("Python received: closed", { exact: false })).toBeVisible();
});
