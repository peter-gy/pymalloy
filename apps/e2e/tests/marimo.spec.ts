import { expect, test } from "./fixture.ts";

test("marimo controls update the widget and reactive Python readback", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sales analysis", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "42", exact: true })).toBeVisible();
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 42}]");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(page.getByRole("table")).toContainText("30");
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 30}]");

  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).check();
  await expect(page.getByRole("alert")).toContainText("missing_source");
  await expect(page.getByText("Python received: error", { exact: false })).toBeVisible();
  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).uncheck();
  await expect(page.getByRole("table")).toContainText("30");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("table")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("marimo-mobile.png"), fullPage: true });
});
