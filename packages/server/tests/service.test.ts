import { expect, test } from "vite-plus/test";
import { CompilerService } from "../src/service.js";
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
            { value: [{ name: "value", type: "INTEGER" }] },
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
    url: "file:///model.malloy",
    source: "run: duckdb.sql('SELECT 42 AS value') -> {select:value}",
  } as const;
  expect(service.request(begin).kind).toBe("needs");
  expect(service.request({ op: "parse", source: "run: missing", url: begin.url }).kind).toBe(
    "parse",
  );
  expect(service.request({ op: "step", fulfilled: { urls: {}, schemas: {} } })).toMatchObject({
    kind: "error",
    message: "Compiler has no pending request",
  });

  expect(finish(service, service.request(begin))).toMatchObject({
    kind: "model",
    queries: [{ name: "run:0", kind: "run" }],
  });
  expect(service.request(begin)).toMatchObject({
    kind: "error",
    message: "Compiler already owns a model",
  });
  const query = finish(service, service.request({ op: "query", givens: {} }));
  expect(query).toMatchObject({ kind: "query", sql: expect.stringContaining("42") });
  expect(finish(service, service.request({ op: "document", givens: {} }))).toMatchObject({
    kind: "document",
    cells: [{ kind: "query", name: "run:0" }],
  });
});
