import { expect, test } from "vite-plus/test";
import { CompilerSession } from "../src/session";
import { connection } from "@malloy-runtime/duckdb";
import type { Response } from "@pymalloy/protocol";

function finish(service: CompilerSession, first: Response): Response {
  let response = first;
  while (response.kind === "needs") {
    response = service.step({
      urls: {},
      schemas: Object.fromEntries(
        response.needs.schemas.map(({ key }) => [
          key,
          { kind: "value", value: [{ name: "value", type: "INTEGER" }] },
        ]),
      ),
    });
  }
  return response;
}

test("an active compiler job survives a rejected concurrent operation", () => {
  const service = new CompilerSession();
  const begin = {
    op: "begin",
    documentKind: "model",
    connection,
    url: "file:///model.malloy",
    source: "run: duckdb.sql('SELECT 42 AS value') -> {select:value}",
  } as const;
  const first = service.start(begin);
  expect(first.kind).toBe("needs");
  expect(
    service.start({ op: "parse", source: "run: missing", url: begin.url, documentKind: "model" }),
  ).toEqual({
    kind: "failure",
    message: "Compiler already has an active job",
  });

  expect(finish(service, first)).toMatchObject({
    kind: "model",
    queries: [{ name: "run:0", kind: "run" }],
  });
  expect(service.start(begin)).toMatchObject({
    kind: "failure",
    message: "Compiler already owns a model",
  });
  const query = finish(service, service.start({ op: "query", givens: {} }));
  expect(query).toMatchObject({ kind: "query", sql: expect.stringContaining("42") });
  expect(finish(service, service.start({ op: "document", givens: {} }))).toMatchObject({
    kind: "document",
    cells: [{ kind: "query", name: "run:0" }],
  });
  service.close();
});

test("closing a compiler settles pending work and is idempotent", () => {
  const service = new CompilerSession();
  expect(
    service.start({
      op: "begin",
      documentKind: "model",
      connection,
      url: "file:///model.malloy",
    }),
  ).toMatchObject({ kind: "needs", needs: { urls: ["file:///model.malloy"] } });
  service.close();
  service.close();
  expect(service.step({ urls: {}, schemas: {} })).toEqual({
    kind: "failure",
    message: "Compiler is closed",
  });
  expect(service.start({ op: "format", source: "run: missing" })).toEqual({
    kind: "failure",
    message: "Compiler is closed",
  });
});

test("completed compiler jobs reject further host answers", () => {
  const service = new CompilerSession();
  expect(service.start({ op: "format", source: "run: missing" }).kind).toBe("format");
  expect(service.step({ urls: {}, schemas: {} })).toEqual({
    kind: "failure",
    message: "Compiler has no pending request",
  });
  service.close();
});

test("compiler diagnostics remain distinct from internal request failures", () => {
  const service = new CompilerSession();
  expect(
    service.start({
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
  expect(service.start({ op: "query", givens: {} })).toEqual({
    kind: "failure",
    message: "Compiler has no model",
  });
});

test("compiler session preserves DuckDB scalar and nested schemas through host answers", () => {
  const service = new CompilerSession();
  let response = service.start({
    op: "begin",
    documentKind: "model",
    connection,
    url: "file:///types.malloy",
    source: `source: typed is duckdb.sql("SELECT TIME '12:34:56.123456' AS clock, INTERVAL '1 microsecond' AS duration, MAP([1::BIGINT], [2::BIGINT]) AS mapping, [TIME '00:00:00.000001'] AS clocks")
    run: typed -> {select: *}`,
  });
  while (response.kind === "needs") {
    response = service.step(
      JSON.parse(
        JSON.stringify({
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
        }),
      ),
    );
  }
  expect(response.kind).toBe("model");
  const inspection = JSON.parse(JSON.stringify(service.start({ op: "inspect" })));
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
    JSON.parse(JSON.stringify(finish(service, service.start({ op: "query", givens: {} })))),
  ).toMatchObject({ kind: "query", name: "run:0", sql: expect.stringContaining('"clock"') });
});
