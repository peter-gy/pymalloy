import { expect, test } from "./fixture";

test("an exported widget hydrates captured imports and synchronizes query changes", async ({
  page,
}) => {
  await page.goto("/lab/tree/exported.ipynb");
  await expect(
    page.getByRole("button", { name: "Python 3 (PyMalloy) | Idle", exact: true }),
  ).toBeVisible();
  const run = async (source: string) => {
    await page.getByRole("textbox").filter({ hasText: source }).click();
    await page.getByRole("button", { name: /Run this cell and advance/ }).click();
  };
  for (const source of [
    "from pathlib import Path",
    "files = {",
    "model_source = ModelSource(",
    "givens = {}",
    "run_0 = MalloyWidget(",
  ])
    await run(source);
  await expect(page.getByRole("table")).toContainText("North");
  await expect(page.getByRole("table")).toContainText("42");
  await page.getByRole("combobox", { name: "Query", exact: true }).selectOption("report.filtered");
  await expect(page.getByRole("table")).toContainText("42");
  await run('run_0.givens = {"region_filter": "South"}');
  await expect(page.getByRole("table")).toContainText("30");
  await run('print("Export query:", run_0.query)');
  await expect(page.getByText("Export query: report.filtered", { exact: true })).toBeVisible();
  await run('print("Export closed")');
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.getByRole("menuitem", { name: "Kernel", exact: true }).click();
  await page.getByRole("menuitem", { name: /Shut Down Kernel/ }).click();
  await expect(page.getByRole("button", { name: "No Kernel", exact: true })).toBeVisible();
});

test("JupyterLab renders, synchronizes, recovers, and closes multiple views", async ({
  page,
}, testInfo) => {
  await page.goto("/lab/tree/sales.ipynb");
  await expect(page.getByRole("tab", { name: "sales.ipynb", exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Python 3 (PyMalloy) | Idle", exact: true }),
  ).toBeVisible();
  const run = async (source: string) => {
    let cell = page.getByRole("textbox");
    for (const line of source.split("\n")) cell = cell.filter({ hasText: line });
    await cell.click();
    await page.getByRole("button", { name: /Run this cell and advance/ }).click();
  };
  await run("import asyncio");
  await expect(page.getByRole("table")).toHaveCount(1);
  await expect(page.getByRole("table")).toContainText("North");
  await expect(page.getByRole("table")).toContainText("42");
  await run('print("Python rows:",');
  await expect(
    page.getByText(
      'Python rows: [{"region": "North", "revenue": 42}, {"region": "South", "revenue": 30}]',
      { exact: true },
    ),
  ).toBeVisible();

  await run('widget.givens = {"region_filter": "South"}');
  await expect(page.getByRole("table")).toContainText("30");
  await run('print("Python filtered:",');
  await expect(page.getByText('Python filtered: [{"revenue": 30}]', { exact: true })).toBeVisible();

  await run('widget.query = "sales.by_region"\ndisplay(widget)');
  await expect(page.getByRole("table")).toHaveCount(2);
  const selectors = page.getByRole("combobox", { name: "Query", exact: true });
  await selectors.first().selectOption("sales.filtered");
  await expect(selectors.last()).toHaveValue("sales.filtered");
  await run('print("Browser selected:",');
  await expect(page.getByText("Browser selected: sales.filtered", { exact: true })).toBeVisible();

  await run('widget.source = "run: missing_source"');
  await expect(page.getByRole("alert")).toHaveCount(2);
  await run('print("Model and data replaced")');
  await expect(page.getByRole("table")).toHaveCount(2);
  await expect(page.getByRole("table").first()).toContainText("70");
  await run('print("Python replacement:",');
  await expect(
    page.getByText(
      'Python replacement: [{"region": "North", "revenue": 70}, {"region": "South", "revenue": 10}]',
      { exact: true },
    ),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("jupyter-multiview.png"), fullPage: true });

  await run("widget.close()");
  await expect(page.getByText("Analysis closed", { exact: true })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.getByRole("menuitem", { name: "Kernel", exact: true }).click();
  await page.getByRole("menuitem", { name: /Shut Down Kernel/ }).click();
  await expect(page.getByRole("button", { name: "No Kernel", exact: true })).toBeVisible();
});

test("a captured Arrow input executes in the browser from a base-only kernel", async ({ page }) => {
  await page.goto("/lab/tree/dataframe.ipynb");
  await expect(
    page.getByRole("button", { name: "Python 3 (PyMalloy) | Idle", exact: true }),
  ).toBeVisible();
  await page.getByRole("textbox").filter({ hasText: "import pyarrow as pa" }).click();
  await page.getByRole("button", { name: /Run this cell and advance/ }).click();
  await expect(page.getByRole("table")).toContainText("32");
  await page.getByRole("textbox").filter({ hasText: 'print("Dataframe rows:' }).click();
  await page.getByRole("button", { name: /Run this cell and advance/ }).click();
  await expect(page.getByText("Dataframe rows: [{'total': 32}]", { exact: true })).toBeVisible();
  await page.getByRole("menuitem", { name: "Kernel", exact: true }).click();
  await page.getByRole("menuitem", { name: /Shut Down Kernel/ }).click();
  await expect(page.getByRole("button", { name: "No Kernel", exact: true })).toBeVisible();
});

test("Jupyter displays authored values through the standard MIME protocol", async ({
  page,
}, testInfo) => {
  await page.goto("/lab/tree/authoring.ipynb");
  const notebook = page.getByRole("tabpanel", { name: "authoring.ipynb", exact: true });
  await expect(notebook).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Python 3 (PyMalloy) | Idle", exact: true }),
  ).toBeVisible();
  const run = async (source: string) => {
    await notebook.getByRole("textbox").filter({ hasText: source }).click();
    await notebook.getByRole("button", { name: /Run this cell and advance/ }).click();
  };
  await run("import pymalloy as pm");
  const views = notebook.getByRole("region", { name: "Malloy query", exact: true });
  await expect(views).toHaveCount(1);
  await expect(views.first().getByLabel("Malloy source", { exact: true })).toHaveText(
    "amount.sum()",
  );
  await run("import pyarrow as pa");
  const draft = views.nth(1);
  await expect(draft.getByRole("status")).toHaveText("Ready to inspect");
  await draft.getByText("Captured inputs", { exact: true }).click();
  await expect(draft).toContainText("orders · 2 captured rows");
  await draft.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(draft.getByRole("table")).toContainText("42");
  await notebook
    .getByRole("textbox")
    .filter({ hasText: /^orders$/ })
    .click();
  await notebook.getByRole("button", { name: /Run this cell and advance/ }).click();
  const source = views.nth(2);
  await expect(source.getByRole("status")).toHaveText("Ready to inspect");
  await source.getByRole("button", { name: "Run query", exact: true }).click();
  await expect(source.getByRole("status")).toHaveText("2 rows");
  await expect(source.getByRole("cell", { name: "20", exact: true })).toBeVisible();
  await expect(source.getByRole("cell", { name: "22", exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("jupyter-grammar-inspector.png"),
    fullPage: true,
  });
  await page.getByRole("menuitem", { name: "Kernel", exact: true }).click();
  await page.getByRole("menuitem", { name: /Shut Down Kernel/ }).click();
  await expect(page.getByRole("button", { name: "No Kernel", exact: true })).toBeVisible();
});
