import type { GivenValue } from "@malloy-runtime/compiler";
export type Given =
  | { type: "null" }
  | { type: "integer"; value: string }
  | { type: "string"; value: string }
  | { type: "number"; value: number }
  | { type: "boolean"; value: boolean }
  | { type: "array"; value: Given[] }
  | { type: "record"; value: Record<string, Given> };
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
