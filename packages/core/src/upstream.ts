import {
  Model,
  modelDefToModelInfo,
  sourceDefToSourceInfo,
  type SourceDef,
  type Parse,
  type FieldDef,
  type AtomicTypeDef,
} from "@malloydata/malloy";
import { prettify } from "@malloydata/malloy/internal";

// Malloy's private metadata and experimental formatter are isolated here so a
// compiler upgrade has one boundary to review against the pinned dependency.
export const formatMalloy = prettify;
export const parseURL = (parse: Parse): string => parse._translator.sourceURL;
export const parseProblems = (parse: Parse) => parse._translator.logger.getLog();

export interface NativeMetadata {
  model: ReturnType<typeof modelDefToModelInfo> | null;
  sources: ReturnType<typeof sourceDefToSourceInfo>[];
}

export function nativeMetadata(model: Model): NativeMetadata {
  const { named, unnamed } = model.queries();
  const queries = [
    ...named.map((name) => model.getPreparedQueryByName(name)),
    ...Array.from({ length: unnamed }, (_, index) => model.getPreparedQueryByIndex(index)),
  ];
  const required = queries.some((query) =>
    [...query.givens.values()].some((given) => given.default === undefined),
  );
  return {
    model: required ? null : modelDefToModelInfo(model._modelDef),
    sources: model.exportedExplores.map((explore) =>
      // SAFETY: Malloy builds exportedExplores from source definitions in model contents.
      sourceDefToSourceInfo(model.getContent(explore.name) as SourceDef),
    ),
  };
}

export function modelImports(model: Model) {
  return (model._modelDef.imports ?? []).map((value) => ({
    url: value.importURL,
    location: value.location,
  }));
}

export function givenDetails(model: Model, name: string) {
  const given = model.givens.get(name)!;
  return {
    type: givenType(given.type),
    required: given.default === undefined,
    default_text: model._modelDef.givens?.[given.id]?.defaultText ?? null,
  };
}

type Given = Model["givens"] extends ReadonlyMap<string, infer Value> ? Value : never;
function givenType(value: Given["type"] | AtomicTypeDef | FieldDef): string {
  if (value.type === "filter expression") return `filter<${value.filterType}>`;
  if (value.type === "record" || (value.type === "array" && "fields" in value)) {
    const fields = value.fields.map((field) => `${field.name} :: ${givenType(field)}`);
    return `{${fields.join(", ")}}${value.type === "array" ? "[]" : ""}`;
  }
  if (value.type === "array") {
    return `${givenType(value.elementTypeDef)}[]`;
  }
  return value.type;
}

export function importedModel(parse: Parse, url: string): Model | undefined {
  const pending = [...parse._translator.childTranslators.values()];
  for (const translator of pending) {
    if (translator.sourceURL === url) {
      return new Model(
        {
          ...translator.modelDef,
          references: translator.references.toArray(),
          imports: translator.imports,
        },
        [],
        [url],
      );
    }
    pending.push(...translator.childTranslators.values());
  }
}
