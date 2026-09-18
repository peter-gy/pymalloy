import { readFile } from "node:fs/promises";
import {
  checkSource,
  formatSource,
  ToolingError,
  CompiledModel,
  type Cell,
  type CheckReport,
  type Column,
  type Diagnostic,
  type GivenValue,
  type Inspection,
  type Position,
  type ReferenceInfo,
  type SourceBundle,
} from "@pymalloy/core";
import { createInterface } from "node:readline";

type Request = { id: number } & (
  | { op: "format"; source: string }
  | { op: "check"; url: string; source: string; position: Position | null; syntax_only: boolean }
  | { op: "load"; url: string; source?: string | null; sources?: Record<string, string> }
  | { op: "inspect"; model: number; position: (Position & { url: string | null }) | null }
  | { op: "release"; model: number }
  | {
      op: "query";
      model: number;
      query: string | null;
      source: string | null;
      givens: Record<string, Value>;
    }
  | {
      op: "document";
      model: number;
      queries: string[];
      givens: Record<string, Value>;
      profile?: "precompiled" | "native";
    }
);
type SchemaResponse = { id: number } & (
  | { columns: Column[]; error?: never }
  | { error: string; columns?: never }
);
interface DocumentResponse {
  cells: Cell[];
  source?: SourceBundle;
}
type Response =
  | { kind: "schema"; sql: string }
  | { kind: "error"; message: string; diagnostics: Diagnostic[] }
  | ({ kind: "result" } & (
      | CheckReport
      | ReturnType<typeof formatSource>
      | Awaited<ReturnType<CompiledModel["query"]>>
      | { model: number; queries: readonly string[] }
      | { inspection: Inspection & Partial<ReferenceInfo> }
      | DocumentResponse
    ))
  | { kind: "result" };

const reader = createInterface({ input: process.stdin });
const lines = reader[Symbol.asyncIterator]();
let requestID = 0;

function send(value: Response) {
  console.log(JSON.stringify({ id: requestID, ...value }));
}

async function receive(): Promise<Request | SchemaResponse | undefined> {
  const line = await lines.next();
  return line.done ? undefined : JSON.parse(line.value);
}

async function describe(sql: string): Promise<Column[]> {
  send({ kind: "schema", sql });
  const response = await receive();
  if (!response || "op" in response || response.id !== requestID)
    throw new Error("Invalid schema response");
  if (response.error !== undefined) throw new Error(response.error);
  return response.columns;
}

type Value =
  | { type: "null" }
  | { type: "integer"; value: string }
  | { type: "string"; value: string }
  | { type: "number"; value: number }
  | { type: "boolean"; value: boolean }
  | { type: "array"; value: Value[] }
  | { type: "record"; value: Record<string, Value> };

function decode(value: Value): GivenValue {
  switch (value.type) {
    case "null":
      return null;
    case "integer":
      return BigInt(value.value);
    case "array":
      return value.value.map(decode);
    case "record":
      return Object.fromEntries(
        Object.entries(value.value).map(([key, item]) => [key, decode(item)]),
      );
    default:
      return value.value;
  }
}

const readURL = async (url: URL) => {
  if (url.protocol !== "file:") throw new Error(`Import '${url}' must be a local file`);
  return readFile(url, "utf8");
};

const models = new Map<number, CompiledModel>();
let nextModel = 0;
try {
  while (true) {
    const request = await receive();
    if (!request) break;
    requestID = request.id;
    try {
      if (!("op" in request)) throw new Error("Expected a compiler request");
      if (request.op === "format") {
        send({ kind: "result", ...formatSource(request.source) });
        continue;
      }
      if (request.op === "check") {
        send({
          kind: "result",
          ...(await checkSource({
            url: new URL(request.url),
            source: request.source,
            position: request.position ?? undefined,
            syntaxOnly: request.syntax_only,
            describe,
            readURL,
          })),
        });
        continue;
      }
      if (request.op === "load") {
        const sources = request.sources;
        const model = await CompiledModel.load({
          url: new URL(request.url),
          source: request.source ?? undefined,
          describe,
          readURL:
            sources === undefined
              ? readURL
              : async (url) => {
                  if (!Object.hasOwn(sources, url.href)) {
                    throw new Error(`Source bundle is missing '${url.href}'`);
                  }
                  return sources[url.href];
                },
        });
        const handle = ++nextModel;
        models.set(handle, model);
        send({ kind: "result", model: handle, queries: model.queries });
        continue;
      }
      const model = models.get(request.model);
      if (!model) {
        throw new Error("Model is closed or does not belong to this session");
      }
      if (request.op === "inspect") {
        const inspection = model.inspect();
        send({
          kind: "result",
          inspection: request.position
            ? {
                ...inspection,
                ...model.reference({
                  ...request.position,
                  url: request.position.url ? new URL(request.position.url) : undefined,
                }),
              }
            : inspection,
        });
      } else if (request.op === "release") {
        models.delete(request.model);
        send({ kind: "result" });
      } else if (request.op === "query" || request.op === "document") {
        const values = request.givens;
        const givens = Object.fromEntries(
          Object.entries(values).map(([name, value]) => [name, decode(value)]),
        );
        if (request.op === "query") {
          send({ kind: "result", ...(await model.query(request.query, request.source, givens)) });
        } else {
          const result: DocumentResponse = {
            cells: await model.document(request.queries, givens),
          };
          if (request.profile === "native") result.source = model.source();
          send({ kind: "result", ...result });
        }
      } else {
        throw new Error("Unknown compiler operation");
      }
    } catch (error) {
      send({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        diagnostics: error instanceof ToolingError ? error.diagnostics : [],
      });
    }
  }
} finally {
  reader.close();
}
