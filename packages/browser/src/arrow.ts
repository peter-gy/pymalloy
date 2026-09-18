import {
  DataType,
  type Field,
  type MapRow,
  type StructRowProxy,
  type Table,
  Type,
  type Vector,
} from "apache-arrow";

export type ResultValue =
  | null
  | string
  | number
  | bigint
  | boolean
  | Date
  | ArrayBufferView
  | ResultValue[]
  | ResultRow;
export interface ResultRow {
  [column: string]: ResultValue;
}

// Arrow exposes untyped cells. Its field schema determines their representation.
function unwrap(value: unknown, field: Field): ResultValue {
  const type = field.type;
  if (value === null || value === undefined) return null;
  if (DataType.isDictionary(type)) {
    return unwrap(value, field.clone({ type: type.dictionary }));
  }
  if (field.metadata.get("ARROW:extension:name") === "arrow.opaque") {
    const metadata = JSON.parse(field.metadata.get("ARROW:extension:metadata") ?? "{}");
    if (metadata.vendor_name === "DuckDB" && ["hugeint", "uhugeint"].includes(metadata.type_name)) {
      if (!(value instanceof Uint8Array)) throw new Error("Expected DuckDB opaque integer bytes");
      const bytes = value;
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const integer = view.getBigUint64(0, true) | (view.getBigUint64(8, true) << 64n);
      return metadata.type_name === "hugeint" ? BigInt.asIntN(128, integer) : integer;
    }
  }
  if (type.typeId === Type.Date || type.typeId === Type.Timestamp) {
    return value instanceof Date ? new Date(value) : new Date(Number(value));
  }
  if (DataType.isDecimal(type)) {
    // SAFETY: Arrow Decimal cells expose the exact unscaled integer through toString().
    const raw = BigInt((value as { toString(): string }).toString());
    const scale = type.scale;
    const negative = raw < 0n;
    const digits = (negative ? -raw : raw).toString().padStart(scale + 1, "0");
    const number = scale > 0 ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
    return negative ? `-${number}` : number;
  }
  if (DataType.isStruct(type)) {
    // SAFETY: Arrow Struct cells index child values by the schema's field names.
    const row = value as StructRowProxy;
    return Object.fromEntries(
      type.children.map((field) => [field.name, unwrap(row[field.name], field)]),
    );
  }
  if (DataType.isMap(type)) {
    const [keyField, valueField] = type.children[0].type.children;
    // SAFETY: Arrow Map cells iterate the key/value pairs declared by their entry schema.
    return Array.from(value as MapRow, ([key, item]) => ({
      key: unwrap(key, keyField),
      value: unwrap(item, valueField),
    }));
  }
  if (DataType.isList(type) || DataType.isFixedSizeList(type)) {
    // SAFETY: Arrow List and FixedSizeList cells iterate values of their child schema.
    return Array.from(value as Vector, (item) => unwrap(item, type.children[0]));
  }
  if (ArrayBuffer.isView(value)) return structuredClone(value);
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "bigint" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  throw new Error(`Unsupported Arrow result type: ${type.toString()}`);
}

export function materialize(table: Table) {
  return {
    columns: table.schema.fields.map((field) => ({
      name: field.name,
      type: field.type.toString(),
    })),
    rows: table
      .toArray()
      .map((row) =>
        Object.fromEntries(
          table.schema.fields.map((field) => [field.name, unwrap(row[field.name], field)]),
        ),
      ),
  };
}
