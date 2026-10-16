import { afterEach, expect, test } from "vite-plus/test";
import { Session } from "@malloy-runtime/node";
import { BrowserModel, open } from "../src/runtime";

const sessions: Session[] = [];
async function model(text: string): Promise<BrowserModel> {
  const session = await Session.open();
  sessions.push(session);
  return new BrowserModel(await session.model({ text }));
}

afterEach(async () => {
  await Promise.all(sessions.splice(0).map((session) => session.close()));
});

test("JSON results retain native columns, exact integer cells and nested values", async () => {
  const compiled = await model(`run: duckdb.sql("""
    SELECT 9007199254740993::BIGINT AS id,
      12.34::DECIMAL(4, 2) AS amount,
      [{'label': 'one', 'values': [1, NULL, 3]}] AS nested
  """) -> {select: id, amount, nested}`);
  const query = compiled.query("null");
  const result = JSON.parse(await query.run("{}"));
  expect(result.columns).toEqual([
    { name: "id", type: "BIGINT" },
    { name: "amount", type: "DECIMAL(4,2)" },
    { name: "nested", type: 'STRUCT("label" VARCHAR, "values" INTEGER[])[]' },
  ]);
  expect(result.malloy.data).toEqual({
    kind: "array_cell",
    array_value: [
      {
        kind: "record_cell",
        record_value: [
          {
            kind: "number_cell",
            number_value: 9007199254740992,
            string_value: "9007199254740993",
            subtype: "bigint",
          },
          { kind: "number_cell", number_value: 12.34, string_value: "12.34", subtype: "decimal" },
          {
            kind: "array_cell",
            array_value: [
              {
                kind: "record_cell",
                record_value: [
                  { kind: "string_cell", string_value: "one" },
                  {
                    kind: "array_cell",
                    array_value: [
                      { kind: "number_cell", number_value: 1, subtype: "integer" },
                      { kind: "null_cell" },
                      { kind: "number_cell", number_value: 3, subtype: "integer" },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  });
  compiled.close();
});

test("metadata snapshots share query descriptors, sources and inspection records", async () => {
  const text = "run: duckdb.sql('SELECT 42 AS n') -> {select: n}";
  const compiled = await model(text);
  expect(JSON.parse(compiled.queries())).toMatchObject([
    { name: "run:0", kind: "run", schema: { fields: [{ name: "n" }] } },
  ]);
  expect(JSON.parse(compiled.source())).toMatchObject({ text, documentKind: "model", imports: {} });
  expect(JSON.parse(await compiled.inspect("{}"))).toMatchObject({
    queries: [{ name: "run:0", kind: "run", schema: { fields: [{ name: "n" }] } }],
  });
  compiled.close();
});

test("closing a model preserves detached results and invalidates retained queries", async () => {
  const compiled = await model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}");
  const query = compiled.query("null");
  const result = JSON.parse(await query.run("{}"));
  compiled.close();
  compiled.close();
  expect(compiled.closed).toBe(true);
  expect(result.malloy.data.array_value[0].record_value[0].number_value).toBe(42);
  await expect(query.run("{}")).rejects.toMatchObject({ message: "Model is closed" });
  expect(() => compiled.source()).toThrow("Model is closed");
});

test("given integers remain exact and parameter variants do not overwrite defaults", async () => {
  const compiled = await model(`##! experimental.givens
    given: cutoff :: number is 0
    source: values is duckdb.sql('SELECT 9007199254740993::BIGINT AS id')
    run: values -> {select: id where: id = $cutoff}
  `);
  const query = compiled.query("null");
  const selected = JSON.stringify({ cutoff: { type: "integer", value: "9007199254740993" } });
  expect(JSON.parse(await query.run(selected)).malloy.data.array_value).toHaveLength(1);
  expect(JSON.parse(await query.run("{}")).malloy.data.array_value).toEqual([]);
  expect(await query.sql(selected)).toContain("9007199254740993");
  const failure = await query
    .run('{"cutoff":{"type":"integer","value":"invalid"}}')
    .catch((error) => error);
  expect(JSON.parse(failure.pymalloyError)).toMatchObject({
    kind: "runtime",
    message: expect.stringContaining("Givens failed validation"),
  });
  compiled.close();
});

test("given names retain authored prototype-property keys", async () => {
  const compiled = await model(`##! experimental.givens
    given: __proto__ :: number is 0
    source: values is duckdb.sql('SELECT 42 AS n')
    run: values -> {select: n where: n = $__proto__}
  `);
  const query = compiled.query("null");
  const result = JSON.parse(await query.run('{"__proto__":{"type":"integer","value":"42"}}'));
  expect(result.malloy.data.array_value).toMatchObject([{ record_value: [{ number_value: 42 }] }]);
  compiled.close();
});

test("selection diagnostics cross the Python boundary as typed records", async () => {
  const compiled = await model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}");
  let failure: unknown;
  try {
    compiled.query('"missing"');
  } catch (error) {
    failure = error;
  }
  expect(failure).toMatchObject({
    name: "PymalloyBrowserError",
    pymalloyError: expect.stringContaining('"kind":"tooling"'),
  });
  expect(() => compiled.query("{")).toThrow("Query selection must be valid JSON");
  const query = compiled.query("null");
  const controller = new AbortController();
  controller.abort();
  await expect(query.run("{}", controller.signal)).rejects.toThrow("aborted");
  expect(JSON.parse(await query.preview(1, "{}")).malloy.data.array_value).toHaveLength(1);
  compiled.close();
});

test("connection options reject malformed JSON and invalid asset records before startup", async () => {
  await expect(open("{")).rejects.toMatchObject({
    name: "PymalloyBrowserError",
    message: "Connection options must be valid JSON",
  });
  await expect(open('{"name":"duckdb","bundles":{"mvp":{"mainModule":12}}}')).rejects.toMatchObject(
    {
      name: "PymalloyBrowserError",
      message: expect.stringContaining("Connection options failed validation"),
    },
  );
});

test("inspection rejects malformed positions through the model boundary", async () => {
  const compiled = await model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}");
  await expect(compiled.inspect('{"position":{"line":"0","character":0}}')).rejects.toMatchObject({
    name: "PymalloyBrowserError",
    message: expect.stringContaining("Inspection failed validation"),
  });
  expect(JSON.parse(await compiled.inspect("{}"))).toMatchObject({ queries: [{ name: "run:0" }] });
  compiled.close();
});
