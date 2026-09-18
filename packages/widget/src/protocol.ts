import type { Model, DuckDBBundles, GivenValue, ResultRow, ResultValue } from "@pymalloy/browser";

export type Diagnostic = ReturnType<Model["inspect"]>["diagnostics"][number];

type Path = Array<string | number>;
type WireValue = null | string | number | boolean | WireValue[] | WireRow;
interface WireRow {
  [column: string]: WireValue;
}
export interface Input {
  revision: number;
  definition_revision: number;
  query: string | null;
  givens: WireRow;
  integer_paths?: Path[];
}
export interface Definition {
  revision: number;
  source: string;
  url?: string | null;
  imports?: Readonly<Record<string, string>> | null;
  files: Record<string, ArrayBufferView | { url: string }>;
}
export interface State {
  revision: number;
  status: "idle" | "loading" | "ready" | "error" | "closed";
  queries: string[];
  sql: string | null;
  columns: string[];
  rows: WireRow[];
  error: string | null;
  diagnostics: Diagnostic[];
  integer_paths?: Path[];
  number_paths?: Array<{ path: Path; value: "nan" | "inf" | "-inf" }>;
}
export interface WidgetModel {
  query: string | null;
  _input: Input | null;
  _definition: Definition | null;
  _runtime: DuckDBBundles | null;
  _state: State | null;
}

export function givens(input: Input): Record<string, GivenValue> {
  const integers = new Set(input.integer_paths?.map((path) => JSON.stringify(path)));
  function decode(value: WireValue, path: Path): GivenValue {
    if (integers.has(JSON.stringify(path))) {
      if (typeof value !== "string") throw new Error("An integer given must contain decimal text");
      return BigInt(value);
    }
    if (Array.isArray(value)) return value.map((item, index) => decode(item, [...path, index]));
    if (value !== null && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, decode(item, [...path, key])]),
      );
    return value;
  }
  return Object.fromEntries(
    Object.entries(input.givens).map(([key, value]) => [key, decode(value, [key])]),
  );
}

export function resultRows(
  rows: ResultRow[],
): Pick<State, "rows" | "integer_paths" | "number_paths"> {
  const integers: Path[] = [];
  const numbers: NonNullable<State["number_paths"]> = [];
  function encode(value: ResultValue, path: Path): WireValue {
    if (typeof value === "bigint") {
      integers.push(path);
      return String(value);
    }
    if (typeof value === "number" && !Number.isFinite(value)) {
      numbers.push({ path, value: Number.isNaN(value) ? "nan" : value > 0 ? "inf" : "-inf" });
      return null;
    }
    if (value instanceof Date) return value.toISOString();
    if (ArrayBuffer.isView(value))
      return Array.from(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
    if (Array.isArray(value)) return value.map((item, index) => encode(item, [...path, index]));
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, encode(item, [...path, key])]),
      );
    return value;
  }
  return {
    rows: rows.map((row, index) =>
      Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key, encode(value, [index, key])]),
      ),
    ),
    integer_paths: integers,
    number_paths: numbers,
  };
}

export function previewRows(state: State): State["rows"] {
  const rows = structuredClone(state.rows.slice(0, 100));
  for (const entry of state.number_paths ?? []) {
    if (Number(entry.path[0]) >= rows.length) continue;
    let parent: WireValue = rows;
    for (const part of entry.path.slice(0, -1)) {
      if (Array.isArray(parent)) parent = parent[Number(part)];
      else if (parent !== null && typeof parent === "object") parent = parent[part];
      else throw new Error("Invalid result value path");
    }
    const value = { nan: "NaN", inf: "Infinity", "-inf": "-Infinity" }[entry.value];
    const key = entry.path.at(-1)!;
    if (Array.isArray(parent)) parent[Number(key)] = value;
    else if (parent !== null && typeof parent === "object") parent[key] = value;
    else throw new Error("Invalid result value path");
  }
  return rows;
}
