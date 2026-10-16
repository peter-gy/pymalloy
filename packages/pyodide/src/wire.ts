import type { ModelSpec } from "@malloy-runtime/browser";
import { decodeGivens, type Given } from "@pymalloy/protocol";
import { z } from "zod";

function record<K extends string, V>(key: z.ZodType<K, string>, value: z.ZodType<V>) {
  // Entry tuples retain authored keys such as __proto__ as own data properties.
  return z
    .instanceof(Object)
    .refine((value) => !Array.isArray(value), "Expected a string-keyed object")
    .transform((value) => Object.entries(value))
    .pipe(z.array(z.tuple([key, value])))
    .transform((entries) => Object.fromEntries(entries));
}

const documentKind = z.enum(["model", "notebook"]);
const position = z.strictObject({
  line: z.number().int().nonnegative(),
  character: z.number().int().nonnegative(),
});
const source = z.strictObject({
  url: z.url(),
  text: z.string(),
  documentKind,
  imports: record(z.url(), z.string()),
});
const remoteURL = z.url({ protocol: /^https?$/ });
const files = record(
  z.string().min(1),
  z.union([
    z.strictObject({ url: remoteURL }),
    z
      .strictObject({ base64: z.base64() })
      .transform(({ base64 }) =>
        Uint8Array.from(atob(base64), (character) => character.charCodeAt(0)),
      ),
  ]),
);
const specOptions = z.strictObject({
  files: files.optional(),
  documentKind: documentKind.optional(),
});
const spec = z.union([
  specOptions.extend({ source }),
  specOptions.extend({ text: z.string(), url: z.url().optional() }),
  specOptions.extend({ url: z.url() }),
]);
const selectedQuery = z.union([z.null(), z.string(), z.strictObject({ malloy: z.string() })]);
const given: z.ZodType<Given> = z.lazy(() =>
  z.discriminatedUnion("type", [
    z.strictObject({ type: z.literal("null") }),
    z.strictObject({ type: z.literal("integer"), value: z.string().regex(/^-?\d+$/) }),
    z.strictObject({ type: z.literal("number"), value: z.number() }),
    z.strictObject({ type: z.literal("string"), value: z.string() }),
    z.strictObject({ type: z.literal("boolean"), value: z.boolean() }),
    z.strictObject({ type: z.literal("array"), value: z.array(given) }),
    z.strictObject({ type: z.literal("record"), value: record(z.string(), given) }),
  ]),
);
const boundGivens = record(z.string(), given);
const inspect = z.strictObject({ position: position.optional(), url: z.url().optional() });
const parse = z.strictObject({
  url: z.url().optional(),
  documentKind: documentKind.optional(),
  position: position.optional(),
});
const check = parse.extend({
  source: source.optional(),
  syntaxOnly: z.boolean().optional(),
  files: files.optional(),
});
const bundle = z.strictObject({ mainModule: remoteURL, mainWorker: remoteURL });
const connection = z.strictObject({
  name: z.string().refine((value) => value.trim().length > 0, "Connection name must be nonempty"),
  bundles: z.strictObject({ mvp: bundle, eh: bundle.optional() }).optional(),
});

function decode<T>(input: string, name: string, schema: z.ZodType<T>): T {
  try {
    return schema.parse(JSON.parse(input));
  } catch (error) {
    if (error instanceof SyntaxError) throw new TypeError(`${name} must be valid JSON`);
    if (error instanceof z.ZodError)
      throw new TypeError(`${name} failed validation: ${error.message}`);
    throw error;
  }
}

export function modelSpec(input: string): ModelSpec {
  return decode(input, "Model", spec);
}

export function selection(input: string) {
  return decode(input, "Query selection", selectedQuery) ?? undefined;
}

export function givens(input: string) {
  return decodeGivens(decode(input, "Givens", boundGivens));
}

export function inspectOptions(input: string) {
  return decode(input, "Inspection", inspect);
}

export function parseOptions(input: string) {
  return decode(input, "Parse options", parse);
}

export function checkOptions(input: string) {
  return decode(input, "Check options", check);
}

export function connectionOptions(input: string) {
  return decode(input, "Connection options", connection);
}
