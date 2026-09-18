import {
  DataType,
  type Field,
  type MapRow,
  type StructRowProxy,
  type Table,
  Type,
  type Vector,
} from "apache-arrow";
import type { Value } from "@malloy-runtime/compiler";

type Decode = (value: unknown) => Value;

// Plan once per field. Arrow exposes untyped cells, with their representation fixed by the schema.
function decoder(field: Field): Decode {
  const type = field.type;
  let decode: Decode;
  if (DataType.isDictionary(type)) return decoder(field.clone({ type: type.dictionary }));
  const opaque =
    field.metadata.get("ARROW:extension:name") === "arrow.opaque"
      ? JSON.parse(field.metadata.get("ARROW:extension:metadata") ?? "{}")
      : undefined;
  if (opaque?.vendor_name === "DuckDB" && ["hugeint", "uhugeint"].includes(opaque.type_name)) {
    decode = (value) => {
      if (!(value instanceof Uint8Array)) throw new Error("Expected DuckDB opaque integer bytes");
      const view = new DataView(value.buffer, value.byteOffset, value.byteLength);
      const integer = view.getBigUint64(0, true) | (view.getBigUint64(8, true) << 64n);
      return opaque.type_name === "hugeint" ? BigInt.asIntN(128, integer) : integer;
    };
  } else if (type.typeId === Type.Date || type.typeId === Type.Timestamp) {
    decode = (value) => (value instanceof Date ? new Date(value) : new Date(Number(value)));
  } else if (DataType.isDecimal(type)) {
    const scale = type.scale;
    decode = (value) => {
      // SAFETY: Arrow Decimal cells expose the unscaled integer through toString().
      const raw = BigInt((value as { toString(): string }).toString());
      const negative = raw < 0n;
      const digits = (negative ? -raw : raw).toString().padStart(scale + 1, "0");
      const number = scale > 0 ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
      return negative ? `-${number}` : number;
    };
  } else if (DataType.isStruct(type)) {
    const children = type.children.map((child) => ({ name: child.name, decode: decoder(child) }));
    decode = (value) => {
      // SAFETY: Arrow Struct cells index child values by schema field names.
      const row = value as StructRowProxy;
      return Object.fromEntries(
        children.map((child) => [child.name, child.decode(row[child.name])]),
      );
    };
  } else if (DataType.isMap(type)) {
    const [keyField, valueField] = type.children[0].type.children;
    const keyDecoder = decoder(keyField),
      valueDecoder = decoder(valueField);
    decode = (value) => {
      // SAFETY: Arrow Map cells iterate the key/value pairs declared by the entry schema.
      return Array.from(value as MapRow, ([key, item]) => ({
        key: keyDecoder(key),
        value: valueDecoder(item),
      }));
    };
  } else if (DataType.isList(type) || DataType.isFixedSizeList(type)) {
    const child = decoder(type.children[0]);
    decode = (value) => {
      // SAFETY: Arrow list cells iterate values declared by the child schema.
      return Array.from(value as Vector, child);
    };
  } else {
    decode = (value) => {
      if (ArrayBuffer.isView(value)) return structuredClone(value);
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "bigint" ||
        typeof value === "boolean"
      )
        return value;
      throw new Error(`Unsupported Arrow result type: ${type.toString()}`);
    };
  }
  return (value) => (value === null || value === undefined ? null : decode(value));
}

export function materialize(table: Table) {
  const columns = table.schema.fields.map((field, index) => ({
    name: field.name,
    type: field.type.toString(),
    values: table.getChildAt(index)!,
    decode: decoder(field),
  }));
  return {
    columns: columns.map(({ name, type }) => ({ name, type })),
    rows: Array.from({ length: table.numRows }, (_, index) =>
      Object.fromEntries(
        columns.map((column) => [column.name, column.decode(column.values.get(index))]),
      ),
    ),
  };
}
