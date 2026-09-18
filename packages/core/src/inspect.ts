import type { Model, Parse } from "@malloydata/malloy";
import { diagnostics, plain, type Locations, type Diagnostic } from "./diagnostics.js";
import { validatePosition } from "./tools.js";
import type { AnnotationInfo, GivenInfo, ImportInfo, Location, Position } from "./metadata.js";
import {
  givenDetails,
  importedModel,
  modelImports,
  nativeMetadata,
  type NativeMetadata,
} from "./upstream.js";

export interface Inspection {
  native: NativeMetadata;
  queries: string[];
  givens: GivenInfo[];
  annotations: AnnotationInfo[];
  model_annotations: AnnotationInfo[];
  dependencies: string[];
  imports: ImportInfo[];
  diagnostics: Diagnostic[];
}

export interface ReferenceInfo {
  reference: {
    text: string;
    kind: string;
    location: Location;
    definition_location: Location | null;
    definition_type: string;
    default_text: string | null;
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
  queries: readonly string[],
  locations: Locations,
  url: URL,
): Inspection {
  return plain(
    {
      native: nativeMetadata(model),
      queries: [...queries],
      givens: [...model.givens.values()].map((given) => ({
        name: given.name,
        ...givenDetails(model, given.name),
        location: given.location ?? null,
        annotations: annotations(given.annotations),
      })),
      annotations: annotations(model.annotations),
      model_annotations: annotations(model.modelAnnotations),
      dependencies: [
        ...new Set(model.fromSources.map((source) => locations.get(source) ?? source)),
      ].filter((source) => source !== url.href),
      imports: modelImports(model),
      diagnostics: diagnostics(model.problems, locations),
    },
    locations,
  );
}

export function referenceAt(
  model: Model,
  parse: Parse,
  position: Position & { url?: URL },
  locations: Locations,
  url: URL,
): ReferenceInfo {
  validatePosition(position);
  const requestedURL = position.url?.href ?? url.href;
  if (requestedURL !== url.href) {
    const imported = importedModel(parse, requestedURL);
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
            definition_location: reference.definitionLocation ?? null,
            definition_type: reference.definitionType,
            default_text: reference.defaultText ?? null,
            annotations: annotations(reference.annotations),
          }
        : null,
      import: imported ? { url: imported.importURL, location: imported.location } : null,
    },
    locations,
  );
}
