import type { WidgetModel } from "../../../packages/widget/src/protocol";
import { expect, test } from "./fixture";
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
    const session = await Session.open({
      bundles: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
    });
    try {
      const source = "run: duckdb.table('data.csv') -> { select: value }";
      const first = await session.model({
        text: source,
        files: { "data.csv": new TextEncoder().encode("value\n42\n") },
      });
      const second = await session.model({
        text: source,
        files: { "data.csv": new TextEncoder().encode("value\n99\n") },
      });
      const values = [];
      for (const model of [first, first, second, first]) {
        values.push((await model.query().run()).rows[0].value);
      }
      first.close();
      const remaining = (await second.query().run()).rows;
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
      const captured = await session.model({
        text: imported,
        files,
      });
      const remoteValues = [
        (await captured.query().run()).rows[0].value,
        (await captured.query().run()).rows[0].value,
      ];
      const refreshed = await session.model({
        text: imported,
        files,
      });
      remoteValues.push((await refreshed.query().run()).rows[0].value);
      const parameterized = `
        ##! experimental.givens
        given: threshold :: number is 0
        source: numbers is duckdb.sql('SELECT 42 AS value')
        query: selected is numbers -> { select: value where: value > $threshold }
        query: other is numbers -> { select: doubled is value * 2 }
      `;
      const model = await session.model({
        text: parameterized,
      });
      const options = { query: "selected", givens: { threshold: 9007199254740993n } };
      const retained = model.query(options.query).run({
        givens: options.givens,
      });
      const inline = model.query(options.query).run({ givens: options.givens });
      options.query = "other";
      options.givens.threshold = 0n;
      const submitted = await Promise.all([retained, inline]);
      const updated = await model.query(options.query).run({
        givens: options.givens,
      });
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
  expect(output.empty.columns).toEqual([{ name: "value", type: "BIGINT" }]);
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
    const session = await Session.open({
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
      const submitted = session.model({
        source: {
          text: source,
          url: options.url,
          imports: options.imports,
        },
        files: options.files,
      });
      options.url = "https://different.example/report.malloy";
      options.imports["file:///project/numbers.malloy"] = "run: missing";
      const model = await submitted;
      const runs = [];
      for (const query of model.queries)
        runs.push(String((await model.query(query.name).run({})).rows[0].value));
      const extended = await model
        .query({
          malloy: "run: numbers -> {select: doubled is value * 2}",
        })
        .run();
      const missing = await session
        .model({
          source: {
            text: "import './parts/base.malloy'",
            url: "file:///project/report.malloy",
            imports: {},
          },
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
        .model({
          source: {
            text: "import './parts/broken.malloy'",
            url: "file:///project/report.malloy",
            imports: { [invalidURL]: "source: broken is undefined_source" },
          },
        })
        .then(
          () => [],
          (error: {
            diagnostics: Array<{
              location: {
                url: string;
              } | null;
            }>;
          }) => error.diagnostics.map((diagnostic) => diagnostic.location?.url),
        );
      const sqlDocument = await (
        await session.model({
          text: ">>>sql connection:duckdb\nSELECT 17 AS answer",
          url: "file:///project/report.malloysql",
        })
      )
        .query()
        .run();
      const ambiguousImport = await session
        .model({
          text: "import 'base.malloy'",
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
  expect(output.missing).toContain("Source bundle is missing");
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
    const opening = Session.open(options);
    options.signal = new AbortController().signal;
    const reason = new Error("Analysis was replaced");
    startup.abort(reason);
    const startupResult = await opening.then(
      () => "resolved",
      (error: Error) => error === reason,
    );
    const lifetime = new AbortController();
    const session = await Session.open({ bundles, signal: lifetime.signal });
    const model = await session.model({
      text: "run: duckdb.sql('SELECT sum(a.i * b.i) AS value FROM range(1000000) a(i), range(1000000) b(i)') -> { select: value }",
    });
    // oxlint-disable-next-line typescript/unbound-method -- Restored below and invoked with the original Worker as receiver.
    const post = Worker.prototype.postMessage;
    let started!: () => void;
    const queryStarted = new Promise<void>((resolve) => {
      started = resolve;
    });
    // Abort after DuckDB receives the query, exercising termination during execution.
    Worker.prototype.postMessage = function (message, transfer) {
      post.call(this, message, Array.isArray(transfer) ? { transfer } : transfer);
      if (message.type === "START_PENDING_QUERY") started();
    };
    const query = model.query();
    const running = query.run();
    const queued = query.run();
    await queryStarted;
    lifetime.abort();
    const results = await Promise.allSettled([running, queued]);
    Worker.prototype.postMessage = post;
    await session.close();
    return {
      startupResult,
      closed: session.closed,
      results: results.map((result) => result.status),
      after: await query.run().then(
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

test("repeated SQL cells observe schema changes and expose detached columns", async ({ page }) => {
  let csv = "value\n42\n";
  await page.route("**/schema.csv", (route) =>
    route.fulfill({ contentType: "text/csv", body: csv }),
  );
  await page.route("**/advance-schema", (route) => {
    csv = "value\nhi\n";
    return route.fulfill({ body: "updated" });
  });
  await page.goto("/runtime.html");
  const results = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const session = await Session.open({
      bundles: {
        mvp: {
          mainModule: location.origin + "/duckdb/duckdb-mvp.wasm",
          mainWorker: location.origin + "/duckdb/duckdb-browser-mvp.worker.js",
        },
      },
    });
    try {
      const model = await session.model({
        text: ">>>sql connection:duckdb\nSELECT * FROM 'data.csv'",
        url: "https://pymalloy.local/query.malloysql",
        files: { "data.csv": { url: location.origin + "/schema.csv" } },
      });
      const first = await model.query().run();
      first.columns[0].type = "changed by caller";
      const repeated = await model.query().run();
      await fetch("/advance-schema");
      const other = await session.model({
        text: "run: duckdb.sql('SELECT 1 AS value') -> {select:value}",
      });
      other.close();
      const changed = await model.query().run();
      return { repeated: repeated.columns, changed: changed.columns, rows: changed.rows };
    } finally {
      await session.close();
    }
  });
  expect(results).toEqual({
    repeated: [{ name: "value", type: "BIGINT" }],
    changed: [{ name: "value", type: "VARCHAR" }],
    rows: [{ value: "hi" }],
  });
});

test("cancelling one browser query preserves its model and queued work", async ({ page }) => {
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/runtime.mjs";
    const { Session } = await import(entry);
    const session = await Session.open({
      bundles: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
    });
    try {
      const model = await session.model({
        text: `
        source: numbers is duckdb.sql('SELECT range AS value FROM range(1000000000000)')
        query: slow is numbers -> {aggregate: total is value.sum()}
        query: fast is duckdb.sql('SELECT 42 AS answer') -> {select: answer}
      `,
      });
      // Abort after dispatch so this exercises an active statement, not the queue.
      const controller = new AbortController();
      // oxlint-disable-next-line typescript/unbound-method -- Restored in finally, called with its original receiver.
      const post = Worker.prototype.postMessage;
      let started!: () => void;
      const dispatched = new Promise<void>((resolve) => {
        started = resolve;
      });
      Worker.prototype.postMessage = function (message, transfer) {
        post.call(this, message, Array.isArray(transfer) ? { transfer } : transfer);
        if (message.type === "START_PENDING_QUERY") started();
      };
      try {
        const running = model.query("slow").run({ signal: controller.signal });
        const queued = model.query("fast").run();
        const outcome = running.then(
          () => "resolved",
          (error: Error) => error.name,
        );
        await dispatched;
        controller.abort();
        const cancelled = await outcome;
        const immediate = model.query("fast").run();
        return {
          cancelled,
          immediate: (await immediate).rows,
          queued: (await queued).rows,
          repeated: (await model.query("fast").run()).rows,
          closed: session.closed,
        };
      } finally {
        Worker.prototype.postMessage = post;
      }
    } finally {
      await session.close();
    }
  });
  expect(output).toEqual({
    cancelled: "AbortError",
    immediate: [{ answer: 42 }],
    queued: [{ answer: 42 }],
    repeated: [{ answer: 42 }],
    closed: false,
  });
});

test("a widget replaces an active query on its retained browser model", async ({ page }) => {
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/widget.mjs";
    const { default: createWidget } = await import(entry);
    const state: WidgetModel = {
      query: null,
      _state: null,
      _runtime: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
      _definition: {
        revision: 1,
        files: {},
        documentKind: "model",
        connectionName: "duckdb",
        source: `
          query: slow is duckdb.sql('SELECT range AS value FROM range(1000000000000)') -> {aggregate: total is value.sum()}
          query: fast is duckdb.sql('SELECT 42 AS answer') -> {select: answer}
        `,
      },
      _input: { revision: 1, definitionRevision: 1, query: "slow", givens: {} },
    };
    const listeners = new Map<string, Set<() => void>>();
    const publications: Array<{
      revision: number;
      status: string;
      value?: number;
      error?: string | null;
    }> = [];
    let finished!: () => void;
    const ready = new Promise<void>((resolve) => {
      finished = resolve;
    });
    const model = {
      get: <K extends keyof WidgetModel>(key: K): WidgetModel[K] => state[key],
      set: <K extends keyof WidgetModel>(key: K, value: WidgetModel[K]) => {
        state[key] = value;
      },
      on: (event: string, callback: () => void) => {
        if (!listeners.has(event)) listeners.set(event, new Set());
        listeners.get(event)!.add(callback);
      },
      off: (event: string, callback: () => void) => listeners.get(event)?.delete(callback),
      save_changes: () => {
        const current = state._state!;
        publications.push({
          revision: current.revision,
          status: current.status,
          value:
            current.result?.data?.kind === "array_cell" &&
            current.result.data.array_value[0]?.kind === "record_cell" &&
            current.result.data.array_value[0].record_value[0]?.kind === "number_cell"
              ? current.result.data.array_value[0].record_value[0].number_value
              : undefined,
          error: current.error,
        });
        if (current.revision === 2 && (current.status === "ready" || current.status === "error"))
          finished();
      },
    };
    // Replace the selection when the slow statement reaches the actual worker.
    // oxlint-disable-next-line typescript/unbound-method -- Restored in finally and invoked with its Worker receiver.
    const post = Worker.prototype.postMessage;
    let replaced = false;
    Worker.prototype.postMessage = function (message, transfer) {
      post.call(this, message, Array.isArray(transfer) ? { transfer } : transfer);
      if (
        !replaced &&
        message.type === "START_PENDING_QUERY" &&
        !message.data[1].startsWith("DESCRIBE")
      ) {
        replaced = true;
        state._input = { definitionRevision: 1, givens: {}, revision: 2, query: "fast" };
        for (const callback of listeners.get("change:_input") ?? []) callback();
      }
    };
    const dispose = await createWidget().initialize({
      model,
      signal: new AbortController().signal,
    });
    try {
      await ready;
      return publications.filter((value) => value.status === "ready" || value.status === "error");
    } finally {
      Worker.prototype.postMessage = post;
      await dispose();
    }
  });
  expect(output).toEqual([{ revision: 2, status: "ready", value: 42, error: null }]);
});

test("a relocated widget executes absolute HTTP data without a native server", async ({ page }) => {
  await page.route("**/remote-values.csv", (route) =>
    route.fulfill({ contentType: "text/csv", body: "value\n42\n" }),
  );
  await page.goto("/runtime.html");
  const output = await page.evaluate(async () => {
    const entry = "/widget.mjs";
    const { default: createWidget } = await import(entry);
    const url = new URL("/remote-values.csv", location.href).href;
    const state: WidgetModel = {
      query: null,
      _state: null,
      _runtime: {
        mvp: {
          mainModule: new URL("/duckdb/duckdb-mvp.wasm", location.href).href,
          mainWorker: new URL("/duckdb/duckdb-browser-mvp.worker.js", location.href).href,
        },
      },
      _definition: {
        revision: 1,
        files: {},
        documentKind: "model",
        connectionName: "warehouse",
        url: "https://relocated.example/analysis.malloy",
        source: `run: warehouse.table(${JSON.stringify(url)}) -> { select: value }`,
        imports: {},
      },
      _input: { revision: 1, definitionRevision: 1, query: null, givens: {} },
    };
    let finished!: () => void;
    const ready = new Promise<void>((resolve) => {
      finished = resolve;
    });
    const dispose = await createWidget().initialize({
      signal: new AbortController().signal,
      model: {
        get: <K extends keyof WidgetModel>(key: K): WidgetModel[K] => state[key],
        set: <K extends keyof WidgetModel>(key: K, value: WidgetModel[K]) => {
          state[key] = value;
        },
        on: () => undefined,
        off: () => undefined,
        save_changes: () => {
          if (state._state?.status === "ready" || state._state?.status === "error") finished();
        },
      },
    });
    try {
      await ready;
      return state._state;
    } finally {
      await dispose();
    }
  });
  expect(output).toMatchObject({
    status: "ready",
    error: null,
    result: {
      data: {
        kind: "array_cell",
        array_value: [
          { kind: "record_cell", record_value: [{ kind: "number_cell", number_value: 42 }] },
        ],
      },
    },
  });
});
