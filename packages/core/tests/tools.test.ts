import { expect, test } from "vite-plus/test";
import {
  CompiledModel,
  checkSource,
  compilerVersion,
  formatSource,
  parseSource,
} from "../src/index.js";

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
  expect(parsed.symbols[1].lens_range).toEqual({
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
  const report = await checkSource(options(text));
  expect(report.ok).toBe(false);
  expect(report.native.model).toBeNull();
  expect(report.diagnostics[0]).toMatchObject({
    code: "source-or-query-not-found",
    severity: "error",
    location: {
      url: url.href,
      range: { start: { line: 0, character: 5 }, end: { line: 0, character: 12 } },
    },
  });
  await expect(CompiledModel.load(options(text))).rejects.toMatchObject({
    name: "ToolingError",
    diagnostics: report.diagnostics,
  });
});

test("valid models expose schemas and required givens before runtime binding", async () => {
  const model = await CompiledModel.load(
    options(
      "##! experimental.givens\ngiven: threshold :: number\n" +
        source.replace("select: value", "select: value where: value > $threshold"),
    ),
  );
  const inspection = model.inspect();
  expect(inspection.native.sources[0]).toMatchObject({
    name: "values",
    schema: {
      fields: [
        { name: "value", kind: "dimension", type: { kind: "number_type", subtype: "integer" } },
      ],
    },
  });
  expect(inspection.native.model).toBeNull();
  expect(inspection.givens).toMatchObject([
    { name: "threshold", type: "number", required: true, default_text: null },
  ]);
  expect(
    (await checkSource(options("##! experimental.givens\ngiven: threshold :: number\n" + source)))
      .ok,
  ).toBe(true);
  await expect(model.query(undefined, undefined, { threshold: "bad" })).rejects.toMatchObject({
    name: "ToolingError",
    diagnostics: [{ code: "runtime-given-bad-value" }],
  });
});

test("references preserve definition locations across imported files", async () => {
  const model = await CompiledModel.load({
    ...options("import 'base.malloy'\nrun: values -> {select: value}"),
    readURL: async () => source,
  });
  expect(model.reference({ line: 1, character: 24 }).reference).toMatchObject({
    text: "value",
    kind: "field",
    location: { url: url.href },
    definition_location: { url: "memory://project/base.malloy" },
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
  const report = await checkSource(options("import 'missing.malloy'"));
  expect(report.diagnostics[0]).toMatchObject({
    code: "import-error",
    location: { url: url.href },
  });
  expect(report.diagnostics[0].message).toContain("memory://project/missing.malloy");
});

test("ad-hoc query errors identify the query text separately from its model", async () => {
  const model = await CompiledModel.load(options());
  await expect(model.query(undefined, "run: missing")).rejects.toMatchObject({
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

test("document checks map embedded Malloy errors to their original lines", async () => {
  const document =
    ">>>markdown\n# Values\n>>>malloy\nsource: values is duckdb.sql('SELECT 42 AS value')\n>>>sql connection:duckdb\nSELECT * FROM %{ values -> {select: missing} }%";
  const documentURL = new URL("memory://project/report.malloynb");
  expect(parseSource(document, { url: documentURL }).diagnostics).toEqual([]);
  const checked = await checkSource({ ...options(document), url: documentURL });
  expect(checked.ok).toBe(false);
  expect(checked.diagnostics[0]).toMatchObject({
    code: "field-not-found",
    location: {
      url: documentURL.href,
      range: { start: { line: 5, character: 36 }, end: { line: 5, character: 43 } },
    },
  });
  const syntax = parseSource(document.replace("select: missing", "select:"), { url: documentURL });
  expect(syntax.diagnostics[0].location?.range.start.line).toBe(5);
});

test("formatting preserves executable meaning and keeps invalid source unchanged", async () => {
  expect(compilerVersion).toBe("0.0.433");
  const formatted = formatSource(source);
  expect(formatted.diagnostics).toEqual([]);
  expect(formatSource(formatted.source).source).toBe(formatted.source);
  const before = await CompiledModel.load(options());
  const after = await CompiledModel.load(options(formatted.source));
  expect((await after.query()).sql).toBe((await before.query()).sql);
  expect(formatSource("source: values is")).toMatchObject({
    source: "source: values is",
    diagnostics: [{ code: "syntax-error", severity: "error" }],
  });
});

test("unexpected host failures remain exceptions", async () => {
  await expect(
    checkSource({
      ...options(),
      source: undefined,
      readURL: async () => {
        throw new TypeError("host reader failure");
      },
    }),
  ).rejects.toThrow(TypeError);
});

test("compiler replacement text repairs a deprecated expression", async () => {
  const text =
    "source: s is duckdb.sql('SELECT 42 AS value')\nrun: s -> {select: n is case when value > 0 then 1 else 0 end}";
  const report = await checkSource(options(text));
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
  const repaired = await checkSource(options(lines.join("\n")));
  expect(repaired.ok).toBe(true);
  expect(repaired.diagnostics).toEqual([]);
});

test("semantic errors inside imports retain the imported file URL", async () => {
  const report = await checkSource({
    ...options("import 'base.malloy'"),
    readURL: async () =>
      "source: s is duckdb.sql('SELECT 42 AS value') extend {dimension: invalid is missing}",
  });
  expect(report.diagnostics[0]).toMatchObject({
    code: "field-not-found",
    location: { url: "memory://project/base.malloy" },
  });
});

test("embedded document diagnostics use codepoint columns after astral text", async () => {
  const text =
    ">>>malloy\nsource: s is duckdb.sql('SELECT 42 AS value')\n>>>sql connection:duckdb\nSELECT '😀', * FROM %{ s -> {select: missing} }%";
  const checked = await checkSource({
    ...options(text),
    url: new URL("memory://project/unicode.malloynb"),
  });
  expect(checked.diagnostics[0].location?.range).toEqual({
    start: { line: 3, character: 36 },
    end: { line: 3, character: 43 },
  });
});

test("connection failures retain compiler locations and the missing connection name", async () => {
  const report = await checkSource(options("source: bad is bigquery.table('project.table')"));
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
  const report = await checkSource(config);
  expect(reads).toEqual([url.href]);
  expect(report).toMatchObject({
    ok: true,
    compiler_version: compilerVersion,
    native: { model: null, sources: [] },
    imports: [{ url: "memory://project/base.malloy", location: { url: url.href } }],
    tables: [{ path: "missing.csv", connection: "duckdb" }],
  });
});

test("given metadata preserves imported defaults and describes compound types", async () => {
  const model = await CompiledModel.load({
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
      default_text: "10 + 5",
      location: { url: "memory://project/base.malloy" },
    },
    { name: "labels", type: "string[]", required: true, default_text: null },
    { name: "session", type: "{tenant :: string}" },
    { name: "rows", type: "{id :: number}[]" },
    { name: "tenant_filter", type: "filter<string>" },
  ]);
});
