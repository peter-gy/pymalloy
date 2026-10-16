import { expect, test as base } from "./fixture";

const test = base.extend<{ pythonLoopDiagnostics: void }>({
  pythonLoopDiagnostics: [
    async ({ page }, use) => {
      const diagnostics: string[] = [];
      page.on("console", (message) => {
        if (/exception in shielded future|Unhandled exception in event loop/.test(message.text()))
          diagnostics.push(message.text());
      });
      await use();
      expect(diagnostics, "Python event loop diagnostics").toEqual([]);
    },
    { auto: true },
  ],
});

declare global {
  interface Window {
    runBrowserPython(source: string): Promise<string>;
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto("/python-api.html");
  await expect(page.getByLabel("Kernel status")).toHaveText("Python ready", { timeout: 120_000 });
});

test("browser Python executes authored models and preserves result values", async ({ page }) => {
  const report = await page.evaluate(() =>
    window.runBrowserPython(`
from decimal import Decimal
candidate = pm.draft().sources(values=pm.sql("SELECT 20 AS amount UNION ALL SELECT 22 AS amount")).queries(
    total=pm.source("values").pipe(pm.view().aggregate(total=pm.col("amount").sum()))
)
async with browser.connect(runtime=runtime) as connection:
    model = await connection.model(candidate)
    result = await model.query("total").run()
    assert result.to_pylist() == [{"total": 42}]
    assert "SUM" in result.sql.upper()
    model.close()
    model = await connection.model('''run: duckdb.sql("""
        SELECT 9007199254740993::BIGINT AS exact_integer,
          {'value': 9007199254740993::BIGINT} AS nested,
          [1, NULL, 3] AS items,
          1.2300::DECIMAL(12,4) AS amount
    """) -> {select: *}''')
    values = (await model.query().run()).to_pylist()
    assert values == [{"exact_integer": 9007199254740993, "nested": {"value": 9007199254740993}, "items": [1, None, 3], "amount": Decimal("1.2300")}], values
    detached = (await model.query().run()).to_pylist()
    values[0]["nested"]["value"] = 0
    assert detached[0]["nested"]["value"] == 9007199254740993
    model = await connection.model("""##! experimental.givens
given: minimum :: number
run: duckdb.sql('SELECT 20 AS amount UNION ALL SELECT 22 AS amount') -> {where: amount >= $minimum aggregate: total is amount.sum()}
""")
    assert (await model.query().run(givens={"minimum": 21})).to_pylist() == [{"total": 22}]
json.dumps({"total": 42, "integer": str(detached[0]["nested"]["value"]), "given": 22})
`),
  );
  expect(JSON.parse(report)).toEqual({ total: 42, integer: "9007199254740993", given: 22 });
});

test("browser Python cancellation settles work and preserves sibling models", async ({ page }) => {
  const report = await page.evaluate(() =>
    window.runBrowserPython(`
from pymalloy.errors import ClosedError
async with browser.connect(runtime=runtime) as connection:
    slow = await connection.model("run: duckdb.sql('SELECT sum(sin(i)) AS value FROM range(10000000000) t(i)') -> {select: value}")
    sibling = await connection.model("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
    task = asyncio.create_task(slow.query().run())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("the cancelled query returned a result")
    assert (await sibling.query().run()).to_pylist() == [{"answer": 42}]
    slow.close()
    try:
        await slow.query().run()
    except ClosedError:
        pass
    else:
        raise AssertionError("the closed model accepted a query")
    assert (await sibling.query().run()).to_pylist() == [{"answer": 42}]
json.dumps({"cancelled": True, "sibling": 42})
`),
  );
  expect(JSON.parse(report)).toEqual({ cancelled: true, sibling: 42 });
});

test("browser Python loads notebook files and compiler tooling", async ({ page }) => {
  const report = await page.evaluate(() =>
    window.runBrowserPython(`
from pathlib import Path
from pymalloy.errors import CompilationError
Path("sales.csv").write_text("region,amount\\nNorth,20\\nNorth,22\\nSouth,30\\n")
Path("sales.malloy").write_text("source: sales is duckdb.table('sales.csv')\\nrun: sales -> {group_by: region aggregate: total is amount.sum() order_by: region}")
async with browser.connect(runtime=runtime) as connection:
    model = await connection.model(Path("sales.malloy"), files={"sales.csv": Path("sales.csv").read_bytes()})
    rows = (await model.query().run()).to_pylist()
    assert rows == [{"region": "North", "total": 42}, {"region": "South", "total": 30}], rows
    inspection = await model.inspect()
    assert inspection.model.sources[0].name == "sales"
    assert inspection.queries[0].name == "run:0"
    assert (await connection.parse("run: missing")).ok
    report = await connection.check("run: missing")
    assert not report.ok
    assert report.diagnostics[0].code == "source-or-query-not-found"
    assert report.diagnostics[0].severity == "error"
    try:
        await connection.model("run: missing")
    except CompilationError as error:
        assert error.diagnostics[0].code == "source-or-query-not-found"
    else:
        raise AssertionError("the invalid model compiled")
    draft = await connection.read_model(Path("sales.malloy"))
    assert draft.path == Path("sales.malloy").resolve()
    assert draft.names == ("sales",)
    reloaded = await connection.model(draft, files={"sales.csv": Path("sales.csv").read_bytes()})
    assert (await reloaded.query().run()).to_pylist() == rows
    formatted = await connection.format("run: duckdb.sql('SELECT 1 AS n') -> {select: n}")
    assert "select: n" in formatted
json.dumps({"rows": rows})
`),
  );
  expect(JSON.parse(report)).toEqual({
    rows: [
      { region: "North", total: 42 },
      { region: "South", total: 30 },
    ],
  });
});

test("closing a browser connection settles its active query", async ({ page }) => {
  const report = await page.evaluate(() =>
    window.runBrowserPython(`
connection = browser.connect(runtime=runtime)
model = await connection.model("run: duckdb.sql('SELECT sum(sin(i)) AS value FROM range(10000000000) t(i)') -> {select: value}")
task = asyncio.create_task(model.query().run())
await asyncio.sleep(0.1)
await asyncio.wait_for(connection.close(), timeout=5)
assert task.done()
outcome, = await asyncio.gather(task, return_exceptions=True)
assert isinstance(outcome, BaseException), outcome
assert connection.closed and model.closed
json.dumps({"closed": True, "settled": True})
`),
  );
  expect(JSON.parse(report)).toEqual({ closed: true, settled: true });
});
