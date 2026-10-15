import { expect, test } from "./fixture";

test("an exported marimo widget shows 42 and then South revenue 30", async ({ page }) => {
  await page.goto("/");
  const analysis = page.getByRole("region", { name: "Malloy query", exact: true });
  await expect(analysis.getByRole("cell", { name: "42", exact: true })).toBeVisible();
  await expect(analysis.getByRole("cell", { name: "North", exact: true })).toBeVisible();
  await analysis.getByRole("combobox", { name: "Query", exact: true }).selectOption("sales.filtered");
  await expect(analysis.getByRole("cell", { name: "42", exact: true })).toBeVisible();
  await expect(analysis.getByRole("cell", { name: "South", exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(analysis.getByRole("cell", { name: "30", exact: true })).toBeVisible();
  await expect(analysis.getByRole("cell", { name: "42", exact: true })).toHaveCount(0);
});
