import type { Annotation, ModelInfo, SourceInfo, FieldInfo } from "@malloydata/malloy-interfaces";
import {
  Model,
  modelDefToModelInfo,
  sourceDefToSourceInfo,
  routeOf,
  payloadOf,
  type SourceDef,
  type MalloyTranslator,
  type ModelDef,
  type FieldDef,
  type AtomicTypeDef,
} from "@malloydata/malloy";
import { prettify } from "@malloydata/malloy/internal";

// Malloy exposes formatting through its experimental subpath. Keep that dependency
// pinned while translation and metadata use the public API.
export const formatMalloy = prettify;

/** @title NativeMetadata */
export interface NativeMetadata {
  model: ModelInfo | null;
  sources: SourceInfo[];
  annotations: AnnotatedObject[];
}

/** Native annotation routes and payloads alongside the untouched stable annotation. */
export interface RoutedAnnotation {
  route: string | null;
  content: string;
  text: string;
}

export interface AnnotatedObject {
  path: string[];
  kind: string;
  annotations: RoutedAnnotation[];
}

function objectAnnotations(sources: SourceInfo[]): AnnotatedObject[] {
  const objects: AnnotatedObject[] = [];
  function add(path: string[], kind: string, notes: Annotation[] = []): void {
    objects.push({
      path,
      kind,
      annotations: notes.map((note) => ({
        route: routeOf(note) ?? null,
        content: payloadOf(note),
        text: note.value,
      })),
    });
  }
  function fields(values: FieldInfo[], parent: string[]): void {
    for (const field of values) {
      const path = [...parent, field.name];
      add(path, field.kind, field.annotations);
      if (field.kind === "join" || field.kind === "view") fields(field.schema.fields, path);
    }
  }
  for (const source of sources) {
    add([source.name], "source", source.annotations);
    fields(source.schema.fields, [source.name]);
  }
  return objects;
}

export function nativeMetadata(model: Model, definition: ModelDef): NativeMetadata {
  const { named, unnamed } = model.queries();
  const queries = [
    ...named.map((name) => model.getPreparedQueryByName(name)),
    ...Array.from({ length: unnamed }, (_, index) => model.getPreparedQueryByIndex(index)),
  ];
  const required = queries.some((query) =>
    [...query.givens.values()].some((given) => given.default === undefined),
  );
  const stable = required ? null : modelDefToModelInfo(definition);
  const entries = new Map(stable?.entries.map((entry) => [entry.name, entry]));
  const sources = model.exportedExplores.map((explore) => {
    const entry = entries.get(explore.name);
    if (entry?.kind === "source") {
      const { kind: _kind, ...source } = entry;
      return source;
    }
    // SAFETY: Malloy builds exportedExplores from source definitions in model contents.
    return sourceDefToSourceInfo(model.getContent(explore.name) as SourceDef);
  });
  return {
    model: stable,
    sources,
    annotations: objectAnnotations(sources),
  };
}

export function modelImports(definition: ModelDef) {
  return (definition.imports ?? []).map((value) => ({
    url: value.importURL,
    location: value.location,
  }));
}

export function givenDetails(given: Given, definition: ModelDef) {
  return {
    type: givenType(given.type),
    required: given.default === undefined,
    defaultText: definition.givens?.[given.id]?.defaultText ?? null,
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

export function importedModel(translator: MalloyTranslator, url: string): Model | undefined {
  const dependency = translator.translatorForDependency(url);
  if (!dependency) return undefined;
  const definition = dependency.translate().modelDef;
  return definition ? new Model(definition, dependency.problems(), [url]) : undefined;
}
