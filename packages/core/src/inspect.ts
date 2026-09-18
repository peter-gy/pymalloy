import type { QueryDescriptor } from "./types";
import type { Model, MalloyTranslator, ModelDef } from "@malloydata/malloy";
import { diagnostics, plain, type Locations, type Diagnostic } from "./diagnostics";
import { validatePosition } from "./tools";
import type {
  AnnotationInfo,
  GivenInfo,
  ImportInfo,
  SourceLocation,
  SourcePosition,
} from "./metadata";
import {
  givenDetails,
  importedModel,
  modelImports,
  nativeMetadata,
  type NativeMetadata,
} from "./upstream";

/** @title Inspection */
export interface Inspection {
  reference?: ReferenceInfo["reference"];
  import?: ReferenceInfo["import"];
  model: NativeMetadata;
  queries: QueryDescriptor[];
  givens: GivenInfo[];
  annotations: AnnotationInfo[];
  modelAnnotations: AnnotationInfo[];
  dependencies: string[];
  imports: ImportInfo[];
  diagnostics: Diagnostic[];
}

/** @title ReferenceInfo */
export interface ReferenceInfo {
  reference: {
    text: string;
    kind: string;
    location: SourceLocation;
    definitionLocation: SourceLocation | null;
    definitionType: string;
    defaultText: string | null;
    annotations: AnnotationInfo[];
  } | null;
  import: ImportInfo | null;
}

function annotations(value: Model["annotations"]): AnnotationInfo[] {
  return value.forRoute().map((note) => ({
    route: note.route,
    text: note.text,
    content: note.content,
    location: note.at,
  }));
}

export function inspectModel(
  model: Model,
  queries: readonly QueryDescriptor[],
  locations: Locations,
  url: URL,
  definition: ModelDef,
): Inspection {
  return plain(
    {
      model: nativeMetadata(model, definition),
      queries: [...queries],
      givens: [...model.givens.values()].map((given) => ({
        name: given.name,
        ...givenDetails(model, definition, given.name),
        location: given.location ?? null,
        annotations: annotations(given.annotations),
      })),
      annotations: annotations(model.annotations),
      modelAnnotations: annotations(model.modelAnnotations),
      dependencies: [
        ...new Set(model.fromSources.map((source) => locations.get(source) ?? source)),
      ].filter((source) => source !== url.href),
      imports: modelImports(definition),
      diagnostics: diagnostics(model.problems, locations),
    },
    locations,
  );
}

export function referenceAt(
  model: Model,
  translator: MalloyTranslator,
  position: SourcePosition & { url?: URL },
  locations: Locations,
  url: URL,
): ReferenceInfo {
  validatePosition(position);
  const requestedURL = position.url?.href ?? url.href;
  if (requestedURL !== url.href) {
    const imported = importedModel(translator, requestedURL);
    if (!imported) return { reference: null, import: null };
    model = imported;
  }
  const reference = model.referenceAt(position);
  const imported = model.getImport(position);
  return plain(
    {
      reference: reference
        ? {
            text: reference.text,
            kind: reference.kind,
            location: reference.location,
            definitionLocation: reference.definitionLocation ?? null,
            definitionType: reference.definitionType,
            defaultText: reference.defaultText ?? null,
            annotations: annotations(reference.annotations),
          }
        : null,
      import: imported ? { url: imported.importURL, location: imported.location } : null,
    },
    locations,
  );
}
