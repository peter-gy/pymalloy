import { compile, drive, check } from "./host";
import { expect, test } from "vite-plus/test";
import { formatSource, parseSource } from "../src/tooling";
const url = new URL("memory://project/model.malloy");
const source = "source: values is duckdb.sql('SELECT 42 AS value')\nrun: values -> {select: value}";
function options(text = source) {
  return {
    url,
    source: text,
    describe: async () => [{ name: "value", type: "INTEGER" }],
    readURL: async (path: URL): Promise<string> => {
      throw new Error(`Missing import: ${path}`);
    },
  };
}
test("syntax reports preserve codepoint coordinates and recover document symbols", () => {
  const text = "source: s is duckdb.sql(\"SELECT '😀' AS face\") run: s -> {select: face}";
  const parsed = parseSource(text, { url });
  expect(parsed.diagnostics).toEqual([]);
  expect(parsed.symbols[1].lensRange).toEqual({
    start: { line: 0, character: 46 },
    end: { line: 0, character: 70 },
  });
  const invalid = parseSource("source: s is", { url });
  expect(invalid.symbols.map((symbol) => symbol.name)).toEqual(["s"]);
  expect(invalid.diagnostics[0]).toMatchObject({
    code: "syntax-error",
    severity: "error",
    location: {
      url: url.href,
      range: { start: { line: 0, character: 12 }, end: { line: 0, character: 12 } },
    },
  });
});
test("syntax reports enumerate imports, tables, and native contextual completions", () => {
  const parsed = parseSource(
    "import 'base.malloy'\nsource: s is duckdb.table('x.csv') extend {\n\n}",
    { url, position: { line: 2, character: 0 } },
  );
  expect(parsed.imports.map((value) => value.url)).toEqual(["memory://project/base.malloy"]);
  expect(parsed.tables.map((value) => [value.connection, value.path])).toEqual([
    ["duckdb", "x.csv"],
  ]);
  expect(parsed.completions).toContainEqual({ type: "explore_property", text: "dimension: " });
  expect(parsed.help?.type).toBe("explore_property");
});
test("semantic checks return actionable diagnostics without executing queries", async () => {
  const text = "run: missing -> {select: value}";
  expect(parseSource(text).diagnostics).toEqual([]);
  const report = await check(options(text));
  expect(report.ok).toBe(false);
  expect(report.model.model).toBeNull();
  expect(report.diagnostics[0]).toMatchObject({
    code: "source-or-query-not-found",
    severity: "error",
    location: {
      url: url.href,
      range: { start: { line: 0, character: 5 }, end: { line: 0, character: 12 } },
    },
  });
  await expect(compile(options(text))).rejects.toMatchObject({
    name: "ToolingError",
    diagnostics: report.diagnostics,
  });
});
test("valid models expose schemas and required givens before runtime binding", async () => {
  const model = await compile(
    options(
      "##! experimental.givens\ngiven: threshold :: number\n" +
        source.replace("select: value", "select: value where: value > $threshold"),
    ),
  );
  const inspection = model.inspect();
  expect(inspection.model.sources[0]).toMatchObject({
    name: "values",
    schema: {
      fields: [
        { name: "value", kind: "dimension", type: { kind: "number_type", subtype: "integer" } },
      ],
    },
  });
  expect(inspection.model.model).toBeNull();
  expect(inspection.givens).toMatchObject([
    { name: "threshold", type: "number", required: true, defaultText: null },
  ]);
  expect(
    (await check(options("##! experimental.givens\ngiven: threshold :: number\n" + source))).ok,
  ).toBe(true);
  await expect(
    drive(
      model.prepare(undefined, {
        givens: { threshold: "bad" },
      }),
    ),
  ).rejects.toMatchObject({
    name: "ToolingError",
    diagnostics: [{ code: "runtime-given-bad-value" }],
  });
});
test("references preserve definition locations across imported files", async () => {
  const model = await compile({
    ...options("import 'base.malloy'\nrun: values -> {select: value}"),
    readURL: async () => source,
  });
  expect(model.reference({ line: 1, character: 24 }).reference).toMatchObject({
    text: "value",
    kind: "field",
    location: { url: url.href },
    definitionLocation: { url: "memory://project/base.malloy" },
  });
  expect(model.reference({ line: 0, character: 10 }).import).toMatchObject({
    url: "memory://project/base.malloy",
  });
  expect(
    model.reference({ url: new URL("memory://project/base.malloy"), line: 1, character: 24 })
      .reference,
  ).toMatchObject({
    text: "value",
    kind: "field",
    location: { url: "memory://project/base.malloy" },
  });
  expect(model.inspect().dependencies).toEqual(["memory://project/base.malloy"]);
});
test("import failures retain their diagnostic source location", async () => {
  const report = await check(options("import 'missing.malloy'"));
  expect(report.diagnostics[0]).toMatchObject({
    code: "import-error",
    location: { url: url.href },
  });
  expect(report.diagnostics[0].message).toContain("memory://project/missing.malloy");
});
test("ad-hoc query errors identify the query text separately from its model", async () => {
  const model = await compile(options());
  await expect(
    drive(
      model.prepare(
        {
          malloy: "run: missing",
        },
        {},
      ),
    ),
  ).rejects.toMatchObject({
    diagnostics: [
      {
        code: "source-or-query-not-found",
        location: {
          url: "memory://pymalloy/query.malloy",
          range: { start: { line: 0, character: 5 }, end: { line: 0, character: 12 } },
        },
      },
    ],
  });
});
test("document diagnostics preserve authored lines and Unicode codepoint columns", async () => {
  const document =
    ">>>markdown\n# Values\n>>>malloy\nsource: values is duckdb.sql('SELECT 42 AS value')\n>>>sql connection:duckdb\nSELECT '😀', * FROM %{ values -> {select: missing} }%";
  const documentURL = new URL("memory://project/report.malloynb");
  expect(parseSource(document, { url: documentURL, documentKind: "notebook" }).diagnostics).toEqual(
    [],
  );
  const checked = await check({ ...options(document), url: documentURL });
  expect(checked.ok).toBe(false);
  expect(checked.diagnostics[0]).toMatchObject({
    code: "field-not-found",
    location: {
      url: documentURL.href,
      range: { start: { line: 5, character: 41 }, end: { line: 5, character: 48 } },
    },
  });
  const syntax = parseSource(document.replace("select: missing", "select:"), {
    url: documentURL,
    documentKind: "notebook",
  });
  expect(syntax.diagnostics[0].location?.range.start.line).toBe(5);
});
test("formatting preserves executable meaning and keeps invalid source unchanged", async () => {
  const formatted = formatSource(source);
  expect(formatted.diagnostics).toEqual([]);
  expect(formatSource(formatted.source).source).toBe(formatted.source);
  const before = await compile(options());
  const after = await compile(options(formatted.source));
  expect((await drive(after.prepare(undefined, {}))).sql).toBe(
    (await drive(before.prepare(undefined, {}))).sql,
  );
  expect(formatSource("source: values is")).toMatchObject({
    source: "source: values is",
    diagnostics: [{ code: "syntax-error", severity: "error" }],
  });
});
test("unexpected host failures remain exceptions", async () => {
  await expect(
    check({
      ...options(),
      source: undefined,
      readURL: async () => {
        throw new TypeError("host reader failure");
      },
    }),
  ).rejects.toThrow("host reader failure");
});
test("compiler replacement text repairs a deprecated expression", async () => {
  const text =
    "source: s is duckdb.sql('SELECT 42 AS value')\nrun: s -> {select: n is case when value > 0 then 1 else 0 end}";
  const report = await check(options(text));
  expect(report.ok).toBe(true);
  expect(report.diagnostics).toMatchObject([
    { code: "sql-case", severity: "warning", replacement: "pick 1 when value > 0 else 0" },
  ]);
  const suggestion = report.diagnostics[0];
  const range = suggestion.location!.range;
  const lines = text.split("\n");
  const line = Array.from(lines[range.start.line]);
  lines[range.start.line] =
    line.slice(0, range.start.character).join("") +
    suggestion.replacement +
    line.slice(range.end.character).join("");
  const repaired = await check(options(lines.join("\n")));
  expect(repaired.ok).toBe(true);
  expect(repaired.diagnostics).toEqual([]);
});
test("semantic errors inside imports retain the imported file URL", async () => {
  const report = await check({
    ...options("import 'base.malloy'"),
    readURL: async () =>
      "source: s is duckdb.sql('SELECT 42 AS value') extend {dimension: invalid is missing}",
  });
  expect(report.diagnostics[0]).toMatchObject({
    code: "field-not-found",
    location: { url: "memory://project/base.malloy" },
  });
});
test("connection failures retain compiler locations and the missing connection name", async () => {
  const report = await check(options("source: bad is bigquery.table('project.table')"));
  expect(report.diagnostics[0]).toMatchObject({
    code: "failed-to-fetch-table-schema",
    severity: "error",
    location: {
      url: url.href,
      range: { start: { line: 0, character: 15 }, end: { line: 0, character: 46 } },
    },
    data: { connections: ["bigquery"] },
  });
  expect(report.diagnostics[0].message).toContain("Connection 'bigquery'");
});
test("checks share source identity and syntax metadata while deferring data access", async () => {
  const reads: string[] = [];
  const config = {
    ...options(),
    source: undefined,
    readURL: async (path: URL) => {
      reads.push(path.href);
      return "import 'base.malloy'\nsource: s is duckdb.table('missing.csv')";
    },
    describe: async (): Promise<never> => {
      throw new Error("Unexpected schema discovery");
    },
    syntaxOnly: true,
  };
  const report = await check(config);
  expect(reads).toEqual([url.href]);
  expect(report).toMatchObject({
    ok: true,
    model: { model: null, sources: [] },
    imports: [{ url: "memory://project/base.malloy", location: { url: url.href } }],
    tables: [{ path: "missing.csv", connection: "duckdb" }],
  });
});
test("given metadata preserves imported defaults and describes compound types", async () => {
  const model = await compile({
    ...options(`##! experimental.givens
import { limit is cap } from 'base.malloy'
given:
  labels :: string[]
  session :: {tenant :: string}
  rows :: {id :: number}[]
  tenant_filter :: filter<string>
`),
    readURL: async () => "##! experimental.givens\ngiven: cap :: number is 10 + 5",
  });
  expect(model.inspect().givens).toMatchObject([
    {
      name: "limit",
      type: "number",
      required: false,
      defaultText: "10 + 5",
      location: { url: "memory://project/base.malloy" },
    },
    { name: "labels", type: "string[]", required: true, defaultText: null },
    { name: "session", type: "{tenant :: string}" },
    { name: "rows", type: "{id :: number}[]" },
    { name: "tenant_filter", type: "filter<string>" },
  ]);
});

test("incomplete imports return native diagnostics instead of failing metadata extraction", () => {
  const parsed = parseSource(source + "\nimport", { url });
  expect(parsed.diagnostics).toContainEqual(
    expect.objectContaining({ code: "syntax-error", severity: "error" }),
  );
});

test("import literal spans address authored Unicode and CRLF notebook text", () => {
  const authored = '>>>markdown\r\n😀 Source notes\r\n>>>malloy\r\nimport "base.malloy"\r\n';
  const parsed = parseSource(authored, {
    url: new URL("memory://project/model.malloynb"),
    documentKind: "notebook",
  });
  expect(parsed.diagnostics).toEqual([]);
  const span = parsed.imports[0].reference;
  expect(Array.from(authored).slice(span.start, span.end).join("")).toBe('"base.malloy"');
});

test("inspection keeps source schemas distinct from named query outputs and caller edits", async () => {
  const text = source + "\nquery: projected is values -> {select: renamed is value}";
  const model = await compile(options(text));
  const inspection = model.inspect();
  expect(inspection.model.sources.map((item) => item.name)).toEqual(["values"]);
  const projected = inspection.model.model?.entries.find((entry) => entry.name === "projected");
  expect(projected).toMatchObject({ schema: { fields: [{ name: "renamed" }] } });
  const stableSource = inspection.model.model?.entries.find((entry) => entry.name === "values");
  if (stableSource?.kind !== "source") throw new Error("Missing source schema");
  stableSource.schema.fields.length = 0;
  expect(inspection.model.sources[0].schema.fields.map((field) => field.name)).toEqual(["value"]);
  inspection.model.sources[0].schema.fields.length = 0;
  expect(model.inspect().model.sources[0].schema.fields.map((field) => field.name)).toEqual([
    "value",
  ]);
  const retained = model.inspect();
  const adhoc = { malloy: "run: values -> {aggregate: total is sum(value)}" };
  await drive(model.prepare(adhoc));
  expect(model.inspect()).toEqual(retained);
  const uninspected = await compile(options(text));
  await drive(uninspected.prepare(adhoc));
  const firstAfterQuery = uninspected.inspect();
  expect(firstAfterQuery.model.sources).toEqual(retained.model.sources);
  expect(firstAfterQuery.queries).toEqual(retained.queries);
});

test("query name collisions remain explainable in check reports", async () => {
  const report = await check(
    options(`
    source: values is duckdb.sql('SELECT 42 AS value') extend {
      view: detail is {select: value}
    }
    query: \`values.detail\` is values -> detail
  `),
  );
  expect(report.ok).toBe(false);
  expect(report.diagnostics).toContainEqual(
    expect.objectContaining({
      severity: "error",
      message: expect.stringContaining("Ambiguous query selector"),
    }),
  );
});
