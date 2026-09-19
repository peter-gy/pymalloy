import { CompiledModel, type Fulfilled } from "../src/index";
import { compile, drive } from "./host";
import { expect, test } from "vite-plus/test";
async function describe() {
  return [{ name: "value", type: "INTEGER" }];
}
test("document compilation binds per-export givens into every selected query", async () => {
  const model = await compile({
    url: new URL("memory://project/parameterized.malloynb"),
    source: `>>>malloy
##! experimental.givens
given: cutoff :: number
source: numbers is duckdb.sql('SELECT 42 AS value')
run: numbers -> {select: value where: value > $cutoff}
>>>sql connection:duckdb
SELECT * FROM %{ numbers -> {select: value where: value > $cutoff} }%
`,
    describe,
    readURL: async () => "",
  });
  const givens = { cutoff: 10 };
  const pending = drive(
    model.document({
      givens: givens,
    }),
  );
  givens.cutoff = 20;
  const cells = await pending;
  expect(cells.map((cell) => cell.kind === "query" && cell.name)).toEqual(["run:0", "sql:0"]);
  for (const cell of cells) {
    expect(cell.kind === "query" && cell.sql).toContain(">10");
  }
  expect(
    await drive(
      model.document({
        givens: { cutoff: 10 },
      }),
    ),
  ).toEqual(cells);
  const changed = await drive(
    model.document({
      queries: ["sql:0"],
      givens: { cutoff: 20 },
    }),
  );
  expect(changed[0].kind === "query" && changed[0].sql).toContain(">20");
  await expect(drive(model.prepare("sql:0", { givens: { cutoff: "invalid" } }))).rejects.toThrow(
    /cutoff/,
  );
  expect(await drive(model.document({ givens: { cutoff: 10 } }))).toEqual(cells);
});
test("loads documents and imports through the supplied URL reader", async () => {
  const files = new Map([
    [
      "https://models.example/report.malloynb",
      `>>>markdown
# Values
>>>malloy
import 'base.malloy'
run: numbers -> { aggregate: total is value.sum() }
>>>markdown
## Entries
>>>sql connection:duckdb
SELECT * FROM %{ numbers -> { select: value } }%
`,
    ],
    ["https://models.example/base.malloy", "source: numbers is duckdb.sql('SELECT 42 AS value')"],
  ]);
  const reads: string[] = [];
  const model = await compile({
    url: new URL("https://models.example/report.malloynb"),
    describe,
    async readURL(url) {
      reads.push(url.href);
      const source = files.get(url.href);
      if (source === undefined) throw new Error(`Missing model: ${url}`);
      return source;
    },
  });
  expect(reads).toEqual([
    "https://models.example/report.malloynb",
    "https://models.example/base.malloy",
  ]);
  expect(model.queries.map((query) => query.name)).toEqual(["run:0", "sql:0"]);
  const cells = await drive(model.document({}));
  expect(cells.map((cell) => cell.kind)).toEqual(["markdown", "query", "markdown", "query"]);
  expect(cells[0]).toEqual({ kind: "markdown", text: "# Values" });
  expect(cells[2]).toEqual({ kind: "markdown", text: "## Entries" });
  expect((await drive(model.prepare("sql:0", {}))).name).toBe("sql:0");
});
test("inline sources use their URL as the base for imports", async () => {
  const reads: string[] = [];
  const model = await compile({
    url: new URL("memory://project/models/query.malloy"),
    source: "import 'base.malloy'\nrun: numbers -> { select: value }",
    describe,
    async readURL(url) {
      reads.push(url.href);
      if (url.href !== "memory://project/models/base.malloy") throw new Error("Unknown model");
      return "source: numbers is duckdb.sql('SELECT 42 AS value')";
    },
  });
  expect(reads).toEqual(["memory://project/models/base.malloy"]);
  expect(model.queries.map((query) => query.name)).toEqual(["run:0"]);
  expect((await drive(model.prepare(undefined, {}))).name).toBe("run:0");
});
test("source bundles replay complete notebooks and nested imports after original sources change", async () => {
  const url = new URL("file:///project/report.malloynb");
  const source = `>>>markdown
# Complete model
>>>malloy
import 'models/base.malloy'
run: numbers -> { aggregate: total is value.sum() }
>>>sql connection:duckdb
SELECT * FROM %{ numbers -> { select: value } }%
`;
  const files = new Map([
    [url.href, source],
    [
      "file:///project/models/base.malloy",
      "import '../data.malloy'\nsource: numbers is data_numbers",
    ],
    ["file:///project/data.malloy", "source: data_numbers is duckdb.sql('SELECT 42 AS value')"],
  ]);
  const original = await compile({
    url,
    describe,
    async readURL(importURL) {
      const content = files.get(importURL.href);
      if (content === undefined) throw new Error(`Missing source '${importURL.href}'`);
      return content;
    },
  });
  const cells = await drive(original.document({}));
  const bundle = original.source();
  files.delete(url.href);
  expect(bundle).toEqual({
    documentKind: "notebook",
    url: url.href,
    text: source,
    imports: Object.fromEntries(files),
  });
  files.clear();
  const replay = await compile({
    url: new URL(bundle.url),
    source: bundle.text,
    describe,
    async readURL(importURL) {
      const content = bundle.imports[importURL.href];
      if (content === undefined) throw new Error(`Missing source '${importURL.href}'`);
      return content;
    },
  });
  expect(await drive(replay.document({}))).toEqual(cells);
  expect(replay.queries.map((query) => query.name)).toEqual(
    original.queries.map((query) => query.name),
  );
  expect(
    (
      await drive(
        replay.prepare(
          {
            malloy: "run: numbers -> { select: value } ",
          },
          {},
        ),
      )
    ).sql,
  ).toEqual(
    (
      await drive(
        original.prepare(
          {
            malloy: "run: numbers -> { select: value } ",
          },
          {},
        ),
      )
    ).sql,
  );
  bundle.imports["file:///project/data.malloy"] = "changed";
  expect(original.source().imports["file:///project/data.malloy"]).toContain("SELECT 42 AS value");
});
test("source captures query extension imports once and preserves earlier snapshots", async () => {
  let reads = 0;
  const host = {
    describe,
    async readURL() {
      reads += 1;
      return "source: extra is duckdb.sql('SELECT 10 AS value')";
    },
  };
  const model = await compile({
    url: new URL("memory://project/root.malloy"),
    source: "source: numbers is duckdb.sql('SELECT 42 AS value')",
    describe,
    async readURL() {
      reads += 1;
      return "source: extra is duckdb.sql('SELECT 10 AS value')";
    },
  });
  const before = model.source();
  const extension = "import 'extra.malloy'\nrun: extra -> {select: value}";
  await drive(
    model.prepare(
      {
        malloy: extension,
      },
      {},
    ),
    host,
  );
  await drive(
    model.prepare(
      {
        malloy: extension,
      },
      {},
    ),
    host,
  );
  expect(reads).toBe(1);
  expect(before.imports).toEqual({});
  expect(model.source().imports["memory://project/extra.malloy"]).toContain("SELECT 10 AS value");
});
test("inline source and an imported physical file can share a URL in a replay bundle", async () => {
  const url = new URL("file:///project/model.malloy");
  const source = "import 'model.malloy'\nrun: numbers -> { select: value }";
  const imported = "source: numbers is duckdb.sql('SELECT 42 AS value')";
  const original = await compile({
    url,
    source,
    describe,
    readURL: async () => imported,
  });
  const bundle = original.source();
  expect(bundle).toEqual({
    documentKind: "model",
    url: url.href,
    text: source,
    imports: { [url.href]: imported },
  });
  const replay = await compile({
    url: new URL(bundle.url),
    source: bundle.text,
    describe,
    async readURL(importURL) {
      const content = bundle.imports[importURL.href];
      if (content === undefined) throw new Error(`Missing source '${importURL.href}'`);
      return content;
    },
  });
  expect(await drive(replay.document({}))).toEqual(await drive(original.document({})));
});
test("reader failures identify the affected import", async () => {
  await expect(
    compile({
      url: new URL("https://models.example/query.malloy"),
      source: "import 'private.malloy'",
      describe,
      async readURL(url) {
        throw new Error(`Access denied: ${url}`);
      },
    }),
  ).rejects.toThrow("Access denied: https://models.example/private.malloy");
});
test("query discovery and documents expose public views", async () => {
  const model = await compile({
    url: new URL("memory://project/model.malloy"),
    source: `source: numbers is duckdb.sql('SELECT 42 AS value') extend {
      private view: hidden is { select: value }
      internal view: internal_values is { select: value }
      view: visible is { select: value }
    }`,
    describe,
    readURL: async () => "",
  });
  expect(model.queries.map((query) => query.name)).toEqual(["numbers.visible"]);
  Reflect.set(model.queries[0], "name", "changed_by_consumer");
  expect(model.queries[0].name).toBe("numbers.visible");
  expect((await drive(model.prepare(undefined, {}))).name).toBe("numbers.visible");
  expect(await drive(model.document({}))).toEqual([
    {
      kind: "query",
      name: "numbers.visible",
      sql: (await drive(model.prepare(undefined, {}))).sql,
    },
  ]);
  expect(
    await drive(
      model.document({
        all: true,
      }),
    ),
  ).toEqual(await drive(model.document({})));
});
test("embedded query SQL preserves literal replacement tokens", async () => {
  const model = await compile({
    url: new URL("memory://project/model.malloynb"),
    source: `>>>malloy
source: numbers is duckdb.sql('SELECT 42 AS value')
run: numbers -> { select: label is '$& $$' }
>>>sql connection:duckdb
SELECT * FROM %{ numbers -> { select: label is '$& $$' } }%`,
    describe,
    readURL: async () => "",
  });
  const direct = await drive(model.prepare("run:0", {}));
  const embedded = await drive(model.prepare("sql:0", {}));
  expect(embedded.sql).toBe(`SELECT * FROM (${direct.sql})`);
});
test("embedded query replacement follows source ranges around comments and Unicode", async () => {
  const model = await compile({
    url: new URL("memory://project/model.malloynb"),
    source: `>>>malloy
source: numbers is duckdb.sql('SELECT 42 AS value')
run: numbers -> { select: value }
>>>sql connection:duckdb
-- %{ numbers -> { select: value } }%
SELECT '😀', * FROM %{ numbers -> { select: value } }% a
CROSS JOIN (%{ numbers -> { select: value } }%) b`,
    describe,
    readURL: async () => "",
  });
  const direct = await drive(model.prepare("run:0", {}));
  expect((await drive(model.prepare("sql:0", {}))).sql).toBe(
    `-- %{ numbers -> { select: value } }%\nSELECT '😀', * FROM (${direct.sql}) a\nCROSS JOIN (${direct.sql}) b`,
  );
});
test.each([
  {
    selector: "run:0",
    source: `source: numbers is duckdb.sql('SELECT 42 AS value')
query: \`run:0\` is numbers -> { select: value }
run: numbers -> { aggregate: total is value.sum() }`,
    extension: "malloy",
  },
  {
    selector: "numbers.values",
    source: `source: numbers is duckdb.sql('SELECT 42 AS value') extend {
  view: values is { select: value }
}
query: \`numbers.values\` is numbers -> { aggregate: total is value.sum() }`,
    extension: "malloy",
  },
  {
    selector: "numbers.nested.values",
    source: `source: \`numbers.nested\` is duckdb.sql('SELECT 42 AS value') extend {
  view: values is { select: value }
}
source: numbers is duckdb.sql('SELECT 42 AS value') extend {
  view: \`nested.values\` is { aggregate: total is value.sum() }
}`,
    extension: "malloy",
  },
  {
    selector: "sql:0",
    source: `>>>malloy
query: \`sql:0\` is duckdb.sql('SELECT 42 AS value') -> { select: value }
>>>sql connection:duckdb
SELECT 1 AS different`,
    extension: "malloynb",
  },
])(
  "rejects ambiguous selector $selector before choosing a query",
  async ({ source, selector, extension }) => {
    await expect(
      compile({
        url: new URL(`memory://project/model.${extension}`),
        source,
        describe,
        readURL: async () => "",
      }),
    ).rejects.toThrow(`Ambiguous query selector '${selector}'`);
  },
);

test("synchronous jobs accept host connection identity, dialect, and field definitions", () => {
  const job = CompiledModel.begin({
    url: new URL("memory://project/model.malloy"),
    source: "run: warehouse.table('project.dataset.orders') -> {select: amount}",
    connection: { name: "warehouse", dialect: "standardsql" },
  });
  let step = job.step();
  while ("needs" in step) {
    const fulfilled: Fulfilled = { urls: {}, schemas: {} };
    for (const schema of step.needs.schemas)
      fulfilled.schemas[schema.key] = {
        value: [{ name: "amount", type: "number", numberType: "integer" }],
      };
    step = job.step(fulfilled);
  }
  const prepared = step.result.prepare().step();
  expect("result" in prepared && prepared.result.malloy?.connection_name).toBe("warehouse");
  expect("result" in prepared && prepared.result.sql).toContain("base.`amount`");
});

test("embedded SQL queries retain compiled schemas while rebinding givens", async () => {
  let schemaAvailable = true;
  const host = {
    describe: async () => {
      if (!schemaAvailable) throw new Error("Schema discovery is unavailable");
      return [{ name: "value", type: "INTEGER" }];
    },
    readURL: async () => "",
  };
  const model = await compile({
    url: new URL("memory://project/embedded.malloynb"),
    source: `>>>malloy
##! experimental.givens
given: cutoff :: number
>>>sql connection:duckdb
SELECT * FROM %{ duckdb.sql('SELECT 42 AS value') -> {select: value where: value > $cutoff} }%`,
    ...host,
  });
  schemaAvailable = false;
  for (const cutoff of [10, 20]) {
    const prepared = await drive(model.prepare("sql:0", { givens: { cutoff } }), host);
    expect(prepared.sql).toContain(`>${cutoff}`);
  }
});
