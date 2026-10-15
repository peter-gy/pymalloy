import { connection } from "./schema";
import { API, sourceDefToSourceInfo } from "@malloydata/malloy";
import type {
  Result as MalloyResult,
  Cell,
  AtomicType,
  Schema,
  DimensionInfo,
} from "@malloydata/malloy-interfaces";
import type { Column, Row, Value } from "@malloy-runtime/compiler";
import { fields } from "./schema";

export function stableResult(
  sql: string,
  columns: Column[],
  rows: Row[],
  template?: MalloyResult,
  connectionName = connection.name,
): MalloyResult {
  const originalSchema: Schema =
    template?.schema ??
    sourceDefToSourceInfo({
      type: "table",
      name: "result",
      tablePath: "result",
      connection: connectionName,
      dialect: connection.dialect,
      fields: fields(columns),
    }).schema;
  function renderFields(definitions: DimensionInfo[], values: Row[]): DimensionInfo[] {
    return definitions.map((field) => {
      return {
        ...field,
        type: renderType(
          field.type,
          values.map((row) => row[field.name]),
        ),
      };
    });
  }
  function renderType(type: AtomicType, values: Value[]): AtomicType {
    // Malloy's renderer requires each field's cells to match its schema type.
    if (
      type.kind === "number_type" &&
      values.some((value) => value !== null && !Number.isFinite(Number(value)))
    )
      return { kind: "string_type" };
    if (type.kind === "array_type")
      return {
        ...type,
        element_type: renderType(
          type.element_type,
          values.flatMap((value) => (Array.isArray(value) ? value : [])),
        ),
      };
    if (type.kind === "record_type")
      return {
        ...type,
        fields: renderFields(
          type.fields,
          values.filter(
            (value): value is Row =>
              value !== null && typeof value === "object" && !Array.isArray(value),
          ),
        ),
      };
    return type;
  }
  const schema: Schema = {
    ...originalSchema,
    fields: originalSchema.fields.map((field) => {
      if (field.kind !== "dimension") throw new Error("Expected a result dimension");
      return {
        ...field,
        type: renderType(
          field.type,
          rows.map((row) => row[field.name]),
        ),
      };
    }),
  };
  function jsonValue(value: Value): Value {
    if (typeof value === "bigint") return String(value);
    if (ArrayBuffer.isView(value))
      return Array.from(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
    if (Array.isArray(value)) return value.map(jsonValue);
    if (value !== null && typeof value === "object" && !(value instanceof Date))
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, jsonValue(item)]));
    return value;
  }
  function cell(value: Value, type: AtomicType, rendered: AtomicType = type): Cell {
    if (value === null) return { kind: "null_cell" };
    switch (type.kind) {
      case "number_type": {
        const number = Number(value);
        const exact =
          typeof value === "bigint" || typeof value === "string" ? String(value) : undefined;
        if (rendered.kind === "string_type")
          return { kind: "string_cell", string_value: exact ?? String(number) };
        return {
          kind: "number_cell",
          number_value: number,
          subtype: typeof value === "bigint" ? "bigint" : type.subtype,
          string_value: exact,
        };
      }
      case "string_type": {
        // DuckDB TIME uses microseconds since midnight in both adapters.
        if (typeof value === "bigint") {
          const negative = value < 0n;
          const micros = negative ? -value : value;
          const hours = micros / 3_600_000_000n;
          const minutes = (micros / 60_000_000n) % 60n;
          const seconds = (micros / 1_000_000n) % 60n;
          const fraction = (micros % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
          value =
            (negative ? "-" : "") +
            [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":") +
            (fraction ? `.${fraction}` : "");
        }
        if (typeof value !== "string") throw new Error("Invalid string in DuckDB result");
        return { kind: "string_cell", string_value: value };
      }
      case "boolean_type":
        return { kind: "boolean_cell", boolean_value: Boolean(value) && value !== "0" };
      case "date_type":
      case "timestamp_type":
      case "timestamptz_type": {
        const date = API.rowDataToDate(value).toISOString();
        return type.kind === "date_type"
          ? { kind: "date_cell", date_value: date }
          : { kind: "timestamp_cell", timestamp_value: date };
      }
      case "array_type":
        if (!Array.isArray(value)) throw new Error("Invalid array in DuckDB result");
        if (rendered.kind !== "array_type") throw new Error("Expected a rendered array type");
        return {
          kind: "array_cell",
          array_value: value.map((item) => cell(item, type.element_type, rendered.element_type)),
        };
      case "record_type": {
        if (typeof value !== "object" || Array.isArray(value))
          throw new Error("Invalid record in DuckDB result");
        if (rendered.kind !== "record_type") throw new Error("Expected a rendered record type");
        // SAFETY: adapter rows follow the record fields in the compiled result schema.
        const row = value as Row;
        return {
          kind: "record_cell",
          record_value: type.fields.map((field, index) =>
            cell(row[field.name], field.type, rendered.fields[index].type),
          ),
        };
      }
      case "sql_native_type":
      case "json_type": {
        // JSON carries exact SQL-native integers as decimal text, including map entries.
        const encoded = JSON.stringify(jsonValue(value));
        return type.kind === "json_type"
          ? { kind: "json_cell", json_value: encoded }
          : { kind: "sql_native_cell", sql_native_value: encoded };
      }
      default:
        throw new Error("Unsupported Malloy result type");
    }
  }
  const data: Cell = {
    kind: "array_cell",
    array_value: rows.map((row) => ({
      kind: "record_cell",
      record_value: originalSchema.fields.map((field, index) => {
        if (field.kind !== "dimension") throw new Error("Expected a result dimension");
        const rendered = schema.fields[index];
        if (rendered.kind !== "dimension") throw new Error("Expected a result dimension");
        return cell(row[field.name], field.type, rendered.type);
      }),
    })),
  };
  return {
    ...template,
    connection_name: template?.connection_name ?? connectionName,
    schema,
    sql,
    data,
  };
}
