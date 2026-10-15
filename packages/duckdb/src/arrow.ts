import { DataType, type Data, type Field, type Table, TimeUnit, Type, Vector } from "apache-arrow";
import type { Value } from "@malloy-runtime/compiler";

type Decode = (index: number) => Value;

function decoder(field: Field, data: Data): Decode {
  const type = field.type;
  const vector = new Vector([data]);
  let decode: Decode;
  const opaque =
    field.metadata.get("ARROW:extension:name") === "arrow.opaque"
      ? JSON.parse(field.metadata.get("ARROW:extension:metadata") ?? "{}")
      : undefined;
  if (DataType.isDictionary(type)) {
    const dictionary = data.dictionary!;
    const chunks = dictionary.data.map((chunk) =>
      decoder(field.clone({ type: type.dictionary }), chunk),
    );
    decode = (index) => {
      let offset = Number(data.values[index]);
      for (let chunk = 0; chunk < chunks.length; chunk++) {
        if (offset < dictionary.data[chunk].length) return chunks[chunk](offset);
        offset -= dictionary.data[chunk].length;
      }
      throw new Error("Invalid Arrow dictionary index");
    };
  } else if (
    opaque?.vendor_name === "DuckDB" &&
    ["hugeint", "uhugeint"].includes(opaque.type_name)
  ) {
    decode = (index) => {
      const value = vector.get(index);
      if (!(value instanceof Uint8Array)) throw new Error("Expected DuckDB opaque integer bytes");
      const view = new DataView(value.buffer, value.byteOffset, value.byteLength);
      const integer = view.getBigUint64(0, true) | (view.getBigUint64(8, true) << 64n);
      return opaque.type_name === "hugeint" ? BigInt.asIntN(128, integer) : integer;
    };
  } else if (DataType.isInterval(type)) {
    const bytes = new DataView(data.values.buffer, data.values.byteOffset, data.values.byteLength);
    // DuckDB emits month/day/nanosecond intervals, whose 16-byte layout Arrow 17 cannot read.
    if (Number(type.unit) === 2) {
      decode = (index) => ({
        months: bytes.getInt32(index * 16, true),
        days: bytes.getInt32(index * 16 + 4, true),
        micros: bytes.getBigInt64(index * 16 + 8, true) / 1000n,
      });
    } else if (Number(type.unit) === 1) {
      decode = (index) => ({
        months: 0,
        days: bytes.getInt32(index * 8, true),
        micros: BigInt(bytes.getInt32(index * 8 + 4, true)) * 1000n,
      });
    } else {
      decode = (index) => ({ months: bytes.getInt32(index * 4, true), days: 0, micros: 0n });
    }
  } else if (DataType.isTime(type)) {
    decode = (index) => {
      const value = BigInt(vector.get(index));
      switch (type.unit) {
        case TimeUnit.SECOND:
          return value * 1_000_000n;
        case TimeUnit.MILLISECOND:
          return value * 1_000n;
        case TimeUnit.MICROSECOND:
          return value;
        case TimeUnit.NANOSECOND:
          return value / 1_000n;
      }
    };
  } else if (type.typeId === Type.Date || type.typeId === Type.Timestamp) {
    decode = (index) => new Date(Number(vector.get(index)));
  } else if (DataType.isDecimal(type)) {
    const scale = type.scale;
    decode = (index) => {
      const raw = BigInt(vector.get(index).toString());
      const negative = raw < 0n;
      const digits = (negative ? -raw : raw).toString().padStart(scale + 1, "0");
      const number = scale > 0 ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits;
      return negative ? `-${number}` : number;
    };
  } else if (DataType.isStruct(type)) {
    const children = type.children.map((child, index) => ({
      name: child.name,
      decode: decoder(child, data.children[index]),
    }));
    decode = (index) =>
      Object.fromEntries(children.map((child) => [child.name, child.decode(index)]));
  } else if (DataType.isMap(type)) {
    const [keyField, valueField] = type.children[0].type.children;
    const key = decoder(keyField, data.children[0].children[0]);
    const value = decoder(valueField, data.children[0].children[1]);
    decode = (index) =>
      Array.from(
        { length: data.valueOffsets[index + 1] - data.valueOffsets[index] },
        (_, offset) => {
          const entry = data.valueOffsets[index] + offset;
          return { key: key(entry), value: value(entry) };
        },
      );
  } else if (DataType.isList(type) || DataType.isFixedSizeList(type)) {
    const child = decoder(type.children[0], data.children[0]);
    const size = DataType.isFixedSizeList(type) ? type.listSize : undefined;
    decode = (index) => {
      const start = size === undefined ? data.valueOffsets[index] : index * size;
      const end = size === undefined ? data.valueOffsets[index + 1] : start + size;
      return Array.from({ length: end - start }, (_, offset) => child(start + offset));
    };
  } else {
    decode = (index) => {
      const value = vector.get(index);
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
  return (index) => (data.getValid(index) ? decode(index) : null);
}

export function materialize(table: Table) {
  return {
    columns: table.schema.fields.map((field) => ({
      name: field.name,
      type: field.type.toString(),
    })),
    rows: table.batches.flatMap((batch) => {
      const columns = batch.schema.fields.map((field, index) => ({
        name: field.name,
        decode: decoder(field, batch.data.children[index]),
      }));
      return Array.from({ length: batch.numRows }, (_, index) =>
        Object.fromEntries(columns.map((column) => [column.name, column.decode(index)])),
      );
    }),
  };
}
