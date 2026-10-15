import { connection } from "./schema";
import { sourceDefToSourceInfo } from "@malloydata/malloy";
import type {
  Result as MalloyResult,
  Cell,
  AtomicType,
  Schema,
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
  const schema: Schema =
    template?.schema ??
    sourceDefToSourceInfo({
      type: "table",
      name: "result",
      tablePath: "result",
      connection: connectionName,
      dialect: connection.dialect,
      fields: fields(columns),
    }).schema;
  function cell(value: Value, type: AtomicType): Cell {
    if (value === null) return { kind: "null_cell" };
    switch (type.kind) {
      case "number_type": {
        const number = Number(value);
        const exact =
          typeof value === "bigint" || typeof value === "string" || !Number.isFinite(number);
        return {
          kind: "number_cell",
          number_value: Number.isFinite(number) ? number : 0,
          subtype: typeof value === "bigint" ? "bigint" : type.subtype,
          string_value: exact
            ? typeof value === "string" || typeof value === "bigint"
              ? String(value)
              : String(number)
            : undefined,
        };
      }
      case "string_type": {
        // DuckDB TIME uses microseconds since midnight in both adapters.
        if (typeof value === "bigint") {
          const hours = value / 3_600_000_000n;
          const minutes = (value / 60_000_000n) % 60n;
          const seconds = (value / 1_000_000n) % 60n;
          const fraction = (value % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
          value =
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
        if (!(value instanceof Date)) throw new Error("Invalid date in DuckDB result");
        return type.kind === "date_type"
          ? { kind: "date_cell", date_value: value.toISOString() }
          : { kind: "timestamp_cell", timestamp_value: value.toISOString() };
      }
      case "array_type":
        if (!Array.isArray(value)) throw new Error("Invalid array in DuckDB result");
        return {
          kind: "array_cell",
          array_value: value.map((item) => cell(item, type.element_type)),
        };
      case "record_type": {
        if (typeof value !== "object" || Array.isArray(value))
          throw new Error("Invalid record in DuckDB result");
        // SAFETY: adapter rows follow the record fields in the compiled result schema.
        const row = value as Row;
        return {
          kind: "record_cell",
          record_value: type.fields.map((field) => cell(row[field.name], field.type)),
        };
      }
      case "sql_native_type":
      case "json_type": {
        // JSON carries exact SQL-native integers as decimal text, including map entries.
        const encoded = JSON.stringify(value, (_key, item) => {
          if (typeof item === "bigint") return String(item);
          if (ArrayBuffer.isView(item))
            return Array.from(new Uint8Array(item.buffer, item.byteOffset, item.byteLength));
          return item;
        });
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
      record_value: schema.fields.map((field) => {
        if (field.kind !== "dimension") throw new Error("Expected a result dimension");
        return cell(row[field.name], field.type);
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
