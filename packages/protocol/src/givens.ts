import type { GivenValue } from "@malloy-runtime/compiler";
/** @public */
export interface NullGiven {
  type: "null";
}
/** @public */
export interface IntegerGiven {
  type: "integer";
  value: string;
}
/** @public */
export interface StringGiven {
  type: "string";
  value: string;
}
/** @public */
export interface NumberGiven {
  type: "number";
  value: number;
}
/** @public */
export interface BooleanGiven {
  type: "boolean";
  value: boolean;
}
/** @public */
export interface ArrayGiven {
  type: "array";
  value: Given[];
}
/** @public */
export interface RecordGiven {
  type: "record";
  value: Record<string, Given>;
}
export type Given =
  | NullGiven
  | IntegerGiven
  | StringGiven
  | NumberGiven
  | BooleanGiven
  | ArrayGiven
  | RecordGiven;
function decodeGiven(value: Given): GivenValue {
  switch (value.type) {
    case "null":
      return null;
    case "integer":
      return BigInt(value.value);
    case "array":
      return value.value.map(decodeGiven);
    case "record":
      return Object.fromEntries(Object.entries(value.value).map(([k, v]) => [k, decodeGiven(v)]));
    default:
      return value.value;
  }
}

export function decodeGivens(givens: Record<string, Given>): Record<string, GivenValue> {
  return Object.fromEntries(
    Object.entries(givens).map(([name, value]) => [name, decodeGiven(value)]),
  );
}
