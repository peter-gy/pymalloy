import { API, sourceDefToSourceInfo } from "@malloydata/malloy";
import type {
  Result as MalloyResult,
  Cell,
  AtomicType,
  Schema,
} from "@malloydata/malloy-interfaces";
import type { Column, Row, Value } from "@malloy-runtime/compiler";
import { fields } from "./schema.js";

export function stableResult(
  sql: string,
  columns: Column[],
  rows: Row[],
  template?: MalloyResult,
): MalloyResult {
  const schema: Schema =
    template?.schema ??
    sourceDefToSourceInfo({
      type: "table",
      name: "result",
      tablePath: "result",
      connection: "duckdb",
      dialect: "duckdb",
      fields: fields(columns),
    }).schema;
  // Patch the owned cell tree in place to retain exact text without duplicating every row.
  function exact(cell: Cell, value: Value, type: AtomicType): void {
    if (cell.kind === "number_cell" && type.kind === "number_type") {
      if (typeof value === "bigint" && cell.subtype !== "bigint") {
        cell.subtype = "bigint";
        cell.string_value = String(value);
      } else if (typeof value === "string") {
        cell.subtype = type.subtype ?? "decimal";
        cell.string_value = value;
      } else if (typeof value === "number" && !Number.isFinite(value)) {
        cell.number_value = 0;
        cell.string_value = String(value);
      }
    } else if (cell.kind === "sql_native_cell" && ArrayBuffer.isView(value)) {
      cell.sql_native_value = JSON.stringify(
        Array.from(new Uint8Array(value.buffer, value.byteOffset, value.byteLength)),
      );
    } else if (
      cell.kind === "record_cell" &&
      type.kind === "record_type" &&
      value &&
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      // SAFETY: mapData validated this record against its Malloy schema.
      const row = value as Row;
      for (let i = 0; i < cell.record_value.length; i++)
        exact(cell.record_value[i], row[type.fields[i].name], type.fields[i].type);
    } else if (cell.kind === "array_cell" && type.kind === "array_type" && Array.isArray(value)) {
      for (let i = 0; i < cell.array_value.length; i++)
        exact(cell.array_value[i], value[i], type.element_type);
    }
  }
  // SAFETY: adapter materialization returns the scalar/list/record shape accepted by Malloy.
  const data = API.util.mapData(rows as Parameters<typeof API.util.mapData>[0], schema);
  if (data.kind === "array_cell") {
    for (let index = 0; index < data.array_value.length; index++) {
      const record = data.array_value[index];
      if (record.kind !== "record_cell") continue;
      for (let i = 0; i < record.record_value.length; i++) {
        const field = schema.fields[i];
        if (field.kind === "dimension")
          exact(record.record_value[i], rows[index][field.name], field.type);
      }
    }
  }
  return { ...template, connection_name: template?.connection_name ?? "duckdb", schema, sql, data };
}
