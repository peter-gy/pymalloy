import { type DocumentLocation, type LogMessage, MalloyError } from "@malloydata/malloy";
import type { Location } from "./metadata.js";

export interface Diagnostic {
  code: string;
  severity: "error" | "warning" | "debug";
  message: string;
  location: Location | null;
  replacement: string | null;
  error_tag: string | null;
  data: unknown;
}

export type Locations = ReadonlyMap<string, string>;

export function plain<T>(value: T, locations: Locations = new Map()): T {
  return JSON.parse(
    JSON.stringify(value, (_key, item) =>
      typeof item === "string" ? (locations.get(item) ?? item) : item,
    ),
  );
}

export function diagnostics(problems: readonly LogMessage[], locations?: Locations): Diagnostic[] {
  return problems.map((problem) =>
    plain(
      {
        code: problem.code,
        severity: problem.severity === "warn" ? ("warning" as const) : problem.severity,
        message: problem.message,
        location: problem.at ?? null,
        replacement: problem.replacement ?? null,
        error_tag: problem.errorTag ?? null,
        data: problem.data ?? null,
      },
      locations,
    ),
  );
}

export class ToolingError extends Error {
  constructor(
    message: string,
    readonly diagnostics: Diagnostic[],
  ) {
    super(message);
    this.name = "ToolingError";
  }
}

export function toolingError(error: unknown, locations?: Locations): never {
  if (error instanceof ToolingError) throw error;
  if (error instanceof MalloyError) {
    throw new ToolingError(error.message, diagnostics(error.problems, locations));
  }
  if (
    error instanceof Error &&
    "code" in error &&
    typeof error.code === "string" &&
    "at" in error
  ) {
    throw new ToolingError(
      error.message,
      diagnostics(
        [
          {
            code: error.code,
            message: error.message,
            severity: "error",
            // SAFETY: MalloyCompileError supplies DocumentLocation here but is not publicly exported.
            at: error.at as DocumentLocation | undefined,
          },
        ],
        locations,
      ),
    );
  }
  throw error;
}

export function offsetDiagnostics(
  problems: Diagnostic[],
  origin: DocumentLocation,
  prefix = 0,
): Diagnostic[] {
  return problems.map((problem) => {
    const mapped = plain(problem);
    if (mapped.location?.url === origin.url) {
      for (const point of [mapped.location.range.start, mapped.location.range.end]) {
        if (point.line === 0)
          point.character = origin.range.start.character + Math.max(0, point.character - prefix);
        point.line += origin.range.start.line;
      }
    }
    return mapped;
  });
}
