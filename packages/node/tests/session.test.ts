import { afterEach, describe, expect, test } from "vite-plus/test";
import { DuckDBInstance } from "@duckdb/node-api";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { Session } from "../src/session.js";

const sessions: Session[] = [];
const directories: string[] = [];
async function session(options: Parameters<typeof Session.create>[0] = {}) {
  const value = await Session.create(options);
  sessions.push(value);
  return value;
}
async function directory() {
  const value = await mkdtemp(resolve(tmpdir(), "pymalloy-node-"));
  directories.push(value);
  return value;
}
const examples = resolve(import.meta.dirname, "../../../examples");

afterEach(async () => {
  await Promise.all(sessions.splice(0).map((value) => value.close()));
  await Promise.all(
    directories.splice(0).map((value) => rm(value, { recursive: true, force: true })),
  );
});

describe("Node Session", () => {
  test("checks drafts, formats source, and inspects SQL without executing it", async () => {
    const runtime = await session({ dataRoot: examples });
    const report = await runtime.check("run: unknown_source", { path: "draft.malloy" });
    expect(report.ok).toBe(false);
    expect(report.diagnostics[0].location?.url).toMatch(/draft.malloy$/);
    const syntax = await runtime.check("source: missing is duckdb.table('absent.csv')", {
      syntaxOnly: true,
    });
    expect(syntax.ok).toBe(true);
    expect(syntax.native.model).toBeNull();
    expect((await runtime.checkFile(resolve(examples, "orders.malloy"))).ok).toBe(true);
    const source = "run: duckdb.sql('SELECT 42 AS value')->{select:value}";
    const formatted = await runtime.format(source);
    expect((await runtime.check(formatted)).ok).toBe(true);
    const model = await runtime.model(formatted);
    const sql = await model.sql();
    expect((await runtime.connection.runAndReadAll(sql)).getRowObjectsJS()).toEqual([
      { value: 42 },
    ]);
    expect(model.inspect().native.model).not.toBeNull();
    expect(model.inspect({ position: { line: 0, character: 0 } })).toHaveProperty("reference");
  });

  test("cancels queued work without invalidating its session", async () => {
    const runtime = await session();
    const source = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }";
    const first = runtime.run(source);
    const controller = new AbortController();
    const cancelled = runtime.run(source, { signal: controller.signal });
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    expect(await first).toEqual([{ value: 42 }]);
    expect(await runtime.run(source)).toEqual([{ value: 42 }]);
    expect(runtime.closed).toBe(false);
  });

  test("bounds active work and preserves ownership of an interrupted borrowed connection", async () => {
    const instance = await DuckDBInstance.create();
    const connection = await instance.connect();
    try {
      const runtime = await session({ connection });
      const model = await runtime.model(
        "run: duckdb.sql('SELECT range AS value FROM range(1000000000000)') -> { aggregate: total is value.sum() }",
      );
      const running = model.run({ timeout: 20 });
      const queued = model.run();
      const failures = await Promise.allSettled([running, queued]);
      expect(failures.map((result) => result.status)).toEqual(["rejected", "rejected"]);
      expect(failures[0]).toMatchObject({ reason: { name: "TimeoutError" } });
      await runtime.close();
      expect(runtime.closed).toBe(true);
      expect(() => model.inspect()).toThrow("Model is closed");
      expect((await connection.runAndReadAll("SELECT 42 AS answer")).getRowObjectsJS()).toEqual([
        { answer: 42 },
      ]);
    } finally {
      connection.closeSync();
      instance.closeSync();
    }
  });

  test("executes exported views and preserves nested result values", async () => {
    const runtime = await session();
    const model = await runtime.load(resolve(examples, "orders.malloy"));
    expect(model.queries).toEqual([
      "orders.by_region",
      "orders.monthly_revenue",
      "orders.region_detail",
    ]);
    expect(await model.run({ query: "orders.by_region" })).toEqual([
      { region: "North", revenue: 105n, order_count: 3n },
      { region: "South", revenue: 95n, order_count: 3n },
    ]);
    expect(await model.run("run: orders -> region_detail")).toEqual([
      {
        region: "North",
        revenue: 105n,
        categories: [
          { category: "Books", revenue: 55n },
          { category: "Games", revenue: 50n },
        ],
      },
      {
        region: "South",
        revenue: 95n,
        categories: [
          { category: "Books", revenue: 55n },
          { category: "Games", revenue: 40n },
        ],
      },
    ]);
  });

  test("binds dataRoot before same-named files in the process directory", async () => {
    const root = await directory();
    const name = `pymalloy-${Date.now()}.csv`;
    const conflict = resolve(process.cwd(), name);
    await writeFile(conflict, "amount\n1\n");
    try {
      await writeFile(resolve(root, name), "amount\n900\n");
      const runtime = await session({ dataRoot: root });
      const source = `run: duckdb.table('${name}') -> { aggregate: total is amount.sum() }`;
      expect(await runtime.run(source)).toEqual([{ total: 900n }]);
    } finally {
      await rm(conflict);
    }
  });

  test("separates inline imports from relative data paths", async () => {
    const models = await directory();
    await writeFile(resolve(models, "base.malloy"), "source: orders is duckdb.table('orders.csv')");
    const runtime = await session({ dataRoot: examples });
    const model = await runtime.model(
      "import 'base.malloy'\nrun: orders -> { aggregate: total is amount.sum() }",
      { baseDir: models },
    );
    expect(await model.run()).toEqual([{ total: 200n }]);
  });

  test("defaults inline imports to dataRoot", async () => {
    const root = await directory();
    await writeFile(
      resolve(root, "base.malloy"),
      "source: numbers is duckdb.sql('SELECT 42 AS value')",
    );
    const runtime = await session({ dataRoot: root });
    const source = "import 'base.malloy'\nrun: numbers -> { select: value }";
    expect(await runtime.run(source)).toEqual([{ value: 42 }]);
    expect(await (await runtime.model(source)).run()).toEqual([{ value: 42 }]);
  });

  test("captures a loaded model's data directory before queued work begins", async () => {
    const root = await directory();
    const other = await directory();
    await writeFile(resolve(root, "values.csv"), "value\n42\n");
    await writeFile(resolve(other, "values.csv"), "value\n99\n");
    await writeFile(
      resolve(root, "model.malloy"),
      "run: duckdb.table('values.csv') -> { select: value }",
    );
    const runtime = await session();
    const previous = process.cwd();
    try {
      process.chdir(root);
      const loading = runtime.load("model.malloy");
      process.chdir(other);
      expect(await (await loading).run()).toEqual([{ value: 42n }]);
    } finally {
      process.chdir(previous);
    }
  });

  test("resolves filename-shaped tables through DuckDB search paths", async () => {
    const runtime = await session({ dataRoot: examples });
    await runtime.connection.run(
      'CREATE SCHEMA "other.space"; CREATE TABLE "other.space"."ORDERS.CSV" AS SELECT 42 AS amount',
    );
    const file = `run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }`;
    expect(await runtime.run(file)).toEqual([{ total: 200n }]);
    await runtime.connection.run(`SET search_path='"other.space"'`);
    expect(await runtime.run(`run: duckdb.table('"orders.csv"') -> { select: amount }`)).toEqual([
      { amount: 42 },
    ]);
    expect(
      await runtime.run(`run: duckdb.table('"other.space"."orders.csv"') -> { select: amount }`),
    ).toEqual([{ amount: 42 }]);
    await runtime.connection.run("SET search_path='main'");
    expect(await runtime.run(file)).toEqual([{ total: 200n }]);
  });

  test("applies per-call givens and serializes concurrent queries", async () => {
    const runtime = await session({ dataRoot: examples });
    const model = await runtime.model(`
      ##! experimental.givens
      given: region_filter :: string is 'North'
      source: orders is duckdb.table('orders.csv')
      run: orders -> {
        where: region = $region_filter
        aggregate: revenue is amount.sum()
      }
    `);
    expect(
      await Promise.all([
        model.run(),
        model.run({ givens: { region_filter: "South" } }),
        model.run(),
      ]),
    ).toEqual([[{ revenue: 105n }], [{ revenue: 95n }], [{ revenue: 105n }]]);
  });

  test("preserves exact integer literals through SQL path binding", async () => {
    const runtime = await session();
    expect(
      await runtime.run(
        `run: duckdb.sql("SELECT 9007199254740993::BIGINT AS value") -> { select: value }`,
      ),
    ).toEqual([{ value: 9007199254740993n }]);
  });

  test("captures query options and nested givens when work is submitted", async () => {
    const runtime = await session();
    const source = `
      ##! experimental.givens
      given: threshold :: number is 0
      source: numbers is duckdb.sql('SELECT 42 AS value')
      query: selected is numbers -> { select: value where: value > $threshold }
      query: other is numbers -> { select: doubled is value * 2 }
    `;
    const model = await runtime.model(source);
    const options = { query: "selected", givens: { threshold: 1 } };
    const first = model.run(options);
    const second = runtime.run(source, options);
    options.query = "other";
    options.givens.threshold = 100;
    expect(await first).toEqual([{ value: 42 }]);
    expect(await second).toEqual([{ value: 42 }]);
    expect(await model.run(options)).toEqual([{ doubled: 84 }]);
  });

  test("materializes dates, timestamps, nulls, and nested lists", async () => {
    const runtime = await session();
    const result = await runtime.run(`
      source: values is duckdb.sql("""
        SELECT DATE '2026-09-10' AS day_value,
          TIMESTAMPTZ '2026-09-10 12:34:56+00' AS instant,
          NULL::VARCHAR AS missing,
          [{'label': 'a', 'values': [1, NULL, 3]}] AS nested
      """)
      run: values -> { select: * }
    `);
    await runtime.close();
    expect(result).toEqual([
      {
        day_value: new Date("2026-09-10T00:00:00Z"),
        instant: new Date("2026-09-10T12:34:56Z"),
        missing: null,
        nested: [{ label: "a", values: [1, null, 3] }],
      },
    ]);
  });

  test("binds reader lists while preserving CTE table identities", async () => {
    const root = await directory();
    await writeFile(resolve(root, "a.csv"), "value\n40\n");
    await writeFile(resolve(root, "b.csv"), "value\n2\n");
    const runtime = await session({ dataRoot: root });
    expect(
      await runtime.run(`
      run: duckdb.sql("SELECT * FROM read_csv(['a.csv', 'b.csv'])") -> {
        aggregate: total is value.sum()
      }
    `),
    ).toEqual([{ total: 42n }]);
    expect(
      await runtime.run(`
      run: duckdb.sql("""WITH "a.csv" AS (SELECT 3 AS value) SELECT * FROM "a.csv" """) -> { select: value }
    `),
    ).toEqual([{ value: 3 }]);
  });

  test("matches CTE names with DuckDB's ASCII identifier rules", async () => {
    const root = await directory();
    await writeFile(resolve(root, "ä.csv"), "value\n42\n");
    const runtime = await session({ dataRoot: root });
    expect(
      await runtime.run(`
        run: duckdb.sql("""WITH "VALUES.CSV" AS (SELECT 3 AS value)
          SELECT * FROM "values.csv" """) -> { select: value }
      `),
    ).toEqual([{ value: 3 }]);
    expect(
      await runtime.run(`
        run: duckdb.sql("""WITH "Ä.csv" AS (SELECT 3 AS value)
          SELECT * FROM 'ä.csv' """) -> { select: value }
      `),
    ).toEqual([{ value: 42n }]);
  });

  test("binds files using the CTE scope of each query and recursive term", async () => {
    const root = await directory();
    await writeFile(resolve(root, "orders.csv"), "value\n42\n");
    const runtime = await session({ dataRoot: root });
    const cases: Array<[string, number[]]> = [
      [`WITH "orders.csv" AS (SELECT * FROM 'orders.csv') SELECT * FROM "orders.csv"`, [42]],
      [
        `WITH "z.csv" AS (SELECT 3 AS value), "a.csv" AS (SELECT * FROM "z.csv") SELECT * FROM "a.csv"`,
        [3],
      ],
      [
        `WITH first AS (SELECT * FROM 'orders.csv'), "orders.csv" AS (SELECT 1 AS value) SELECT * FROM first`,
        [42],
      ],
      [
        `WITH RECURSIVE "orders.csv" AS (SELECT * FROM 'orders.csv' UNION ALL SELECT value + 1 FROM "orders.csv" WHERE value < 44) SELECT * FROM "orders.csv"`,
        [42, 43, 44],
      ],
      [
        `WITH "orders.csv" AS (SELECT 3 AS value) SELECT * FROM (WITH "orders.csv" AS (SELECT * FROM "orders.csv") SELECT * FROM "orders.csv")`,
        [3],
      ],
      [`WITH "orders.csv" AS (SELECT 1 AS value) SELECT * FROM query_table('orders.csv')`, [42]],
      [
        `WITH "orders.csv" AS (SELECT 3 AS value) SELECT * FROM (WITH RECURSIVE "orders.csv" AS (SELECT * FROM "orders.csv" UNION ALL SELECT value + 1 FROM "orders.csv" WHERE value < 5) SELECT * FROM "orders.csv")`,
        [3, 4, 5],
      ],
    ];
    for (const [sql, expected] of cases) {
      const rows = await runtime.run(`source: numbers is duckdb.sql("""${sql}\n""")
run: numbers -> {select: value order_by: value}`);
      expect(rows.map((row) => Number(row.value))).toEqual(expected);
    }
  });

  test("retains temporary tables and transactions on borrowed connections", async () => {
    const instance = await DuckDBInstance.create();
    const connection = await instance.connect();
    try {
      await connection.run("SET TimeZone = 'Europe/Zurich'");
      await connection.run(
        "CREATE TEMP TABLE numbers(value BIGINT); INSERT INTO numbers VALUES (40), (2); BEGIN",
      );
      const runtime = await session({ connection });
      const model = await runtime.model(
        "run: duckdb.table('numbers') -> { aggregate: total is value.sum() }",
      );
      expect(await model.run()).toEqual([{ total: 42n }]);
      await connection.run("INSERT INTO numbers VALUES (10)");
      expect(await model.run()).toEqual([{ total: 52n }]);
      await runtime.close();
      await connection.run("ROLLBACK");
      expect(
        (
          await connection.runAndReadAll(
            "SELECT sum(value) AS total, current_setting('TimeZone') AS timezone FROM numbers",
          )
        ).getRowObjectsJS(),
      ).toEqual([{ total: 42n, timezone: "Europe/Zurich" }]);
    } finally {
      connection.closeSync();
      instance.closeSync();
    }
  });

  test("keeps filename-shaped database tables addressable", async () => {
    const runtime = await session({ dataRoot: await directory() });
    await runtime.connection.run('CREATE TABLE "ITEMS.CSV" AS SELECT 42 AS value');
    expect(await runtime.run(`run: duckdb.table('"items.csv"') -> { select: value }`)).toEqual([
      { value: 42 },
    ]);
  });

  test("recovers after model and query errors and invalidates closed models", async () => {
    const runtime = await session({ dataRoot: examples });
    await expect(runtime.model("source: broken is")).rejects.toThrow();
    const model = await runtime.model(
      "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    );
    await expect(model.run({ query: "missing" })).rejects.toThrow("Unknown query");
    expect(await model.run()).toEqual([{ total: 200n }]);
    model.close();
    model.close();
    await expect(model.run()).rejects.toThrow("Model is closed");
    const retained = await runtime.model(
      "run: duckdb.sql('SELECT 42 AS value') -> { select: value }",
    );
    const running = retained.run();
    const closing = runtime.close();
    expect(await running).toEqual([{ value: 42 }]);
    await closing;
    await runtime.close();
    await expect(retained.run()).rejects.toThrow("Model is closed");
    await expect(runtime.run("run: broken")).rejects.toThrow("Session is closed");
  });

  test("executes document COPY into the configured data directory", async () => {
    const root = await directory();
    await writeFile(resolve(root, "source.csv"), "value\n40\n2\n");
    const path = resolve(root, "copy.malloynb");
    await writeFile(
      path,
      `>>>sql connection: duckdb\nCOPY (SELECT * FROM 'source.csv') TO 'result.csv' (FORMAT CSV, HEADER)\n`,
    );
    const runtime = await session({ dataRoot: root });
    const model = await runtime.load(path);
    expect(await model.sql({ query: "sql:1" })).toContain("COPY");
    await expect(readFile(resolve(root, "result.csv"))).rejects.toMatchObject({ code: "ENOENT" });
    expect(await model.run({ query: "sql:1" })).toEqual([]);
    expect(await readFile(resolve(root, "result.csv"), "utf8")).toBe("value\n40\n2\n");
  });
});
