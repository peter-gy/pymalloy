import { expect, test } from "./fixture";

test("JupyterLite executes and synchronizes widgets through its Pyodide comm manager", async ({
  page,
}, testInfo) => {
  test.setTimeout(240_000);
  await page.goto("/lab/index.html?path=sales.ipynb");
  await expect(page.getByRole("tab", { name: "sales.ipynb", exact: true })).toBeVisible();
  await expect(page.getByText("Python (Pyodide) | Idle", { exact: true })).toBeVisible({
    timeout: 120_000,
  });
  const run = async (source: string) => {
    await page.getByRole("textbox").filter({ hasText: source }).click();
    await page.getByRole("button", { name: /Run this cell and advance/ }).click();
  };
  await run("import micropip");
  await expect(page.getByText(/^Browser wheel ready:/)).toBeVisible({
    timeout: 120_000,
  });
  await run("from IPython.display import display");
  await expect(page.getByRole("table")).toContainText("42");
  const readback = async (source: string, expected: string) => {
    await expect
      .poll(async () => {
        await run(source);
        await expect(page.getByText("Python (Pyodide) | Idle", { exact: true })).toBeVisible();
        return page.getByText(expected, { exact: true }).count();
      })
      .toBe(1);
  };
  await readback(
    'print("Python received:",',
    'Python received: [{"region": "North", "revenue": 42}, {"region": "South", "revenue": 30}]',
  );
  await run('print("South selected")');
  await expect(page.getByRole("table")).toContainText("30");
  await expect(page.getByRole("table")).not.toContainText("North");
  await readback('print("Python filtered:",', 'Python filtered: [{"revenue": 30}]');
  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("sales.by_region");
  await expect(page.getByRole("table")).toContainText("North");
  await run('print("Browser selected:",');
  await expect(page.getByText("Browser selected: sales.by_region", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("jupyterlite-widget.png"), fullPage: true });
  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("");
  await expect(page.getByRole("table")).toHaveCount(0);
  await readback('print("Browser selected:",', "Browser selected: None");
  await run("widget.close()");
  await expect(page.getByText("Analysis closed", { exact: true })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});
