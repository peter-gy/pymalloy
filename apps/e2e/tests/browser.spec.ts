import { expect, test } from "./fixture.ts";

test("retained models own competing file mappings and preserve exact result values", async ({
  page,
}) => {
  const requested: string[] = [];
  let importRequests = 0;
  await page.route("**/remote-model.malloy", (route) =>
    route.fulfill({
      contentType: "text/plain",
      body: `source: remote is duckdb.sql('SELECT ${++importRequests} AS value')`,
    }),
  );
  page.on("request", (request) => requested.push(new URL(request.url()).pathname));
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const session = await Session.create({
      bundles: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
    });
    try {
      const source = "run: duckdb.table('data.csv') -> { select: value }";
      const first = await session.model(source, {
        files: { "data.csv": new TextEncoder().encode("value\n42\n") },
      });
      const second = await session.model(source, {
        files: { "data.csv": new TextEncoder().encode("value\n99\n") },
      });
      const values = [];
      for (const model of [first, first, second, first]) {
        values.push((await model.run()).rows[0].value);
      }
      first.close();
      const remaining = (await second.run()).rows;
      const exact = await session.run(`run: duckdb.sql("""
        SELECT 170141183460469231731687303715884105727::HUGEINT AS signed_value,
          340282366920938463463374607431768211455::UHUGEINT AS unsigned_value,
          -12345678901234567890.123456789::DECIMAL(38, 9) AS decimal_value,
          TIMESTAMP '2024-02-03 04:05:06.123456' AS timestamp_value,
          DATE '2024-02-03' AS date_value,
          [9007199254740993::BIGINT] AS nested_value
      """) -> { select: * }`);
      const empty = await session.run(
        "run: duckdb.sql('SELECT 42::BIGINT AS value WHERE false') -> { select: value }",
      );
      const imported = "import 'remote.malloy'\nrun: remote -> {select: value}";
      const files = {
        "remote.malloy": { url: new URL("/remote-model.malloy", location.href).href },
      };
      const captured = await session.model(imported, { files });
      const remoteValues = [
        (await captured.run()).rows[0].value,
        (await captured.run()).rows[0].value,
      ];
      const refreshed = await session.model(imported, { files });
      remoteValues.push((await refreshed.run()).rows[0].value);
      const parameterized = `
        ##! experimental.givens
        given: threshold :: number is 0
        source: numbers is duckdb.sql('SELECT 42 AS value')
        query: selected is numbers -> { select: value where: value > $threshold }
        query: other is numbers -> { select: doubled is value * 2 }
      `;
      const model = await session.model(parameterized);
      const options = { query: "selected", givens: { threshold: 9007199254740993n } };
      const retained = model.run(options);
      const inline = session.run(parameterized, options);
      options.query = "other";
      options.givens.threshold = 0n;
      const submitted = await Promise.all([retained, inline]);
      const updated = await model.run(options);
      return JSON.parse(
        JSON.stringify(
          {
            values,
            remaining,
            remoteValues,
            exact: exact.rows,
            empty,
            submitted: submitted.map((result) => ({ rows: result.rows, sql: result.sql })),
            updated: updated.rows,
          },
          // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Playwright JSON transport needs decimal text for bigint cells.
          (_key, value) => (typeof value === "bigint" ? String(value) : value),
        ),
      );
    } finally {
      await session.close();
    }
  });
  expect(output.values.map(String)).toEqual(["42", "42", "99", "42"]);
  expect(output.remoteValues.map(String)).toEqual(["1", "1", "2"]);
  expect(output.submitted.map((result: { rows: [] }) => result.rows)).toEqual([[], []]);
  for (const result of output.submitted) expect(result.sql).toContain("9007199254740993");
  expect(output.updated.map((row: { doubled: number | bigint }) => String(row.doubled))).toEqual([
    "84",
  ]);
  expect(importRequests).toBe(2);
  expect(output.remaining.map((row: { value: unknown }) => String(row.value))).toEqual(["99"]);
  expect(output.exact).toEqual([
    {
      signed_value: "170141183460469231731687303715884105727",
      unsigned_value: "340282366920938463463374607431768211455",
      decimal_value: "-12345678901234567890.123456789",
      timestamp_value: "2024-02-03T04:05:06.123Z",
      date_value: "2024-02-03T00:00:00.000Z",
      nested_value: ["9007199254740993"],
    },
  ]);
  expect(output.empty.rows).toEqual([]);
  expect(output.empty.columns).toEqual([{ name: "value", type: "Int64" }]);
  expect(requested).toContain("/duckdb/duckdb-mvp.wasm");
  expect(requested).toContain("/duckdb/duckdb-browser-mvp.worker.js");
});

test("captured documents retain imports, source identity, and literal data paths", async ({
  page,
}) => {
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const session = await Session.create({
      bundles: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
    });
    try {
      const text = new TextEncoder().encode("value\n42\n");
      const remote = await session.run(
        `run: duckdb.table('${new URL("/sales.csv", location.href).href}') -> {aggregate: total is amount.sum()}`,
        { files: {} },
      );
      const paths = [];
      for (const path of ["../numbers.csv", "/exports/numbers.csv", "parts/../numbers.csv"]) {
        const result = await session.run(`run: duckdb.table('${path}') -> {select: value}`, {
          files: { [path]: text },
        });
        paths.push(String(result.rows[0].value));
      }
      const source = `>>>markdown
# Captured document
>>>malloy
import './parts/base.malloy'
run: numbers -> {select: value}
>>>sql connection:duckdb
SELECT * FROM %{ numbers -> {select: value} }%
`;
      const options = {
        url: "file:///project/report.malloynb",
        imports: {
          "file:///project/parts/base.malloy":
            "import '../numbers.malloy'\nsource: numbers is imported_numbers",
          "file:///project/numbers.malloy":
            "source: imported_numbers is duckdb.table('../numbers.csv')",
        },
        files: { "../numbers.csv": text },
      };
      const submitted = session.model(source, options);
      options.url = "https://different.example/report.malloy";
      options.imports["file:///project/numbers.malloy"] = "run: missing";
      const model = await submitted;
      const runs = [];
      for (const query of model.queries)
        runs.push(String((await model.run({ query })).rows[0].value));
      const extended = await model.run("run: numbers -> {select: doubled is value * 2}");
      const missing = await session
        .model("import './parts/base.malloy'", {
          url: "file:///project/report.malloy",
          imports: {},
          files: {
            "parts/base.malloy": new TextEncoder().encode(
              "source: wrong is duckdb.sql('SELECT 1')",
            ),
          },
        })
        .then(
          () => "resolved",
          (error: Error) => error.message,
        );
      const invalidURL = "file:///project/parts/broken.malloy";
      const diagnostics = await session
        .model("import './parts/broken.malloy'", {
          url: "file:///project/report.malloy",
          imports: { [invalidURL]: "source: broken is undefined_source" },
        })
        .then(
          () => [],
          (error: { diagnostics: Array<{ location: { url: string } | null }> }) =>
            error.diagnostics.map((diagnostic) => diagnostic.location?.url),
        );
      const sqlDocument = await session.run(">>>sql connection:duckdb\nSELECT 17 AS answer", {
        url: "file:///project/report.malloysql",
        imports: {},
      });
      const ambiguousImport = await session
        .model("import 'base.malloy'", {
          files: { "base.malloy": text, "./base.malloy": text },
        })
        .then(
          () => "resolved",
          (error: Error) => error.message,
        );
      return {
        paths,
        remote: String(remote.rows[0].total),
        runs,
        extended: String(extended.rows[0].doubled),
        missing,
        diagnostics,
        sql: String(sqlDocument.rows[0].answer),
        ambiguousImport,
      };
    } finally {
      await session.close();
    }
  });
  expect(output.paths).toEqual(["42", "42", "42"]);
  expect(output.remote).toBe("20");
  expect(output.runs).toEqual(["42", "42"]);
  expect(output.extended).toBe("84");
  expect(output.missing).toContain("not present in captured source");
  expect(output.diagnostics).toContain("file:///project/parts/broken.malloy");
  expect(output.sql).toBe("17");
  expect(output.ambiguousImport).toContain("matches multiple virtual files");
});

test("session abort settles running and queued browser work and releases models", async ({
  page,
}) => {
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const bundles = {
      mvp: {
        mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
        mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
      },
    };
    const startup = new AbortController();
    const options = { bundles, signal: startup.signal };
    const opening = Session.create(options);
    options.signal = new AbortController().signal;
    const reason = new Error("Analysis was replaced");
    startup.abort(reason);
    const startupResult = await opening.then(
      () => "resolved",
      (error: Error) => error === reason,
    );
    const lifetime = new AbortController();
    const session = await Session.create({ bundles, signal: lifetime.signal });
    const model = await session.model(
      "run: duckdb.sql('SELECT sum(a.i * b.i) AS value FROM range(1000000) a(i), range(1000000) b(i)') -> { select: value }",
    );
    // oxlint-disable-next-line typescript/unbound-method -- Restored below and invoked with the original Worker as receiver.
    const post = Worker.prototype.postMessage;
    let started!: () => void;
    const queryStarted = new Promise<void>((resolve) => {
      started = resolve;
    });
    // Abort after DuckDB receives the query, exercising termination during execution.
    Worker.prototype.postMessage = function (message, transfer) {
      post.call(this, message, Array.isArray(transfer) ? { transfer } : transfer);
      if (message.type === "RUN_QUERY") started();
    };
    const running = model.run();
    const queued = model.run();
    await queryStarted;
    lifetime.abort();
    const results = await Promise.allSettled([running, queued]);
    Worker.prototype.postMessage = post;
    await session.close();
    return {
      startupResult,
      closed: session.closed,
      results: results.map((result) => result.status),
      after: await model.run().then(
        () => "resolved",
        (error: Error) => error.message,
      ),
    };
  });
  expect(output).toEqual({
    startupResult: true,
    closed: true,
    results: ["rejected", "rejected"],
    after: "Model is closed",
  });
});
