import { expect, test } from "vite-plus/test";
import { CompilerService } from "../src/service";
import { connection } from "@malloy-runtime/duckdb";
import type { Response } from "@pymalloy/protocol";

function finish(service: CompilerService, first: Response): Response {
  let response = first;
  while (response.kind === "needs") {
    response = service.request({
      op: "step",
      fulfilled: {
        urls: {},
        schemas: Object.fromEntries(
          response.needs.schemas.map(({ key }) => [
            key,
            { kind: "value", value: [{ name: "value", type: "INTEGER" }] },
          ]),
        ),
      },
    });
  }
  return response;
}

test("a compiler service replaces abandoned work and retains its model after rejected operations", () => {
  const service = new CompilerService();
  const begin = {
    op: "begin",
    documentKind: "model",
    connection,
    url: "file:///model.malloy",
    source: "run: duckdb.sql('SELECT 42 AS value') -> {select:value}",
  } as const;
  expect(service.request(begin).kind).toBe("needs");
  expect(
    service.request({ op: "parse", source: "run: missing", url: begin.url, documentKind: "model" })
      .kind,
  ).toBe("parse");
  expect(service.request({ op: "step", fulfilled: { urls: {}, schemas: {} } })).toMatchObject({
    kind: "failure",
    message: "Compiler has no pending request",
  });

  expect(finish(service, service.request(begin))).toMatchObject({
    kind: "model",
    queries: [{ name: "run:0", kind: "run" }],
  });
  expect(service.request(begin)).toMatchObject({
    kind: "failure",
    message: "Compiler already owns a model",
  });
  const query = finish(service, service.request({ op: "query", givens: {} }));
  expect(query).toMatchObject({ kind: "query", sql: expect.stringContaining("42") });
  expect(finish(service, service.request({ op: "document", givens: {} }))).toMatchObject({
    kind: "document",
    cells: [{ kind: "query", name: "run:0" }],
  });
});

test("compiler diagnostics remain distinct from internal request failures", () => {
  const service = new CompilerService();
  expect(
    service.request({
      op: "begin",
      documentKind: "model",
      connection,
      url: "file:///model.malloy",
      source: "run: missing",
    }),
  ).toMatchObject({
    kind: "error",
    diagnostics: [expect.objectContaining({ severity: "error" })],
  });
  expect(service.request({ op: "query", givens: {} })).toEqual({
    kind: "failure",
    message: "Compiler has no model",
  });
});

test("compiler service preserves DuckDB scalar and nested schemas across JSON frames", () => {
  const service = new CompilerService();
  let response = service.request({
    op: "begin",
    documentKind: "model",
    connection,
    url: "file:///types.malloy",
    source: `source: typed is duckdb.sql("SELECT TIME '12:34:56.123456' AS clock, INTERVAL '1 microsecond' AS duration, MAP([1::BIGINT], [2::BIGINT]) AS mapping, [TIME '00:00:00.000001'] AS clocks")
    run: typed -> {select: *}`,
  });
  while (response.kind === "needs") {
    response = service.request(
      JSON.parse(
        JSON.stringify({
          op: "step",
          fulfilled: {
            urls: {},
            schemas: Object.fromEntries(
              response.needs.schemas.map(({ key }) => [
                key,
                {
                  kind: "value",
                  value: [
                    { name: "clock", type: "TIME" },
                    { name: "duration", type: "INTERVAL" },
                    { name: "mapping", type: "MAP(BIGINT, BIGINT)" },
                    { name: "clocks", type: "TIME[]" },
                  ],
                },
              ]),
            ),
          },
        }),
      ),
    );
  }
  expect(response.kind).toBe("model");
  const inspection = JSON.parse(JSON.stringify(service.request({ op: "inspect" })));
  expect(inspection).toMatchObject({
    kind: "inspection",
    inspection: {
      model: {
        sources: [
          {
            name: "typed",
            schema: {
              fields: [
                { name: "clock", type: { kind: "string_type" } },
                { name: "duration", type: { kind: "sql_native_type", sql_type: "INTERVAL" } },
                { name: "mapping", type: { kind: "sql_native_type", sql_type: "MAP" } },
                {
                  name: "clocks",
                  type: { kind: "array_type", element_type: { kind: "string_type" } },
                },
              ],
            },
          },
        ],
      },
    },
  });
  expect(
    JSON.parse(JSON.stringify(finish(service, service.request({ op: "query", givens: {} })))),
  ).toMatchObject({ kind: "query", name: "run:0", sql: expect.stringContaining('"clock"') });
});
