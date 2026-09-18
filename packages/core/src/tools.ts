import { Malloy } from "@malloydata/malloy";
import { formatMalloy, parseProblems } from "./upstream.js";
import type { Position, Range, ImportInfo } from "./metadata.js";
import { diagnostics, ToolingError, offsetDiagnostics, type Diagnostic } from "./diagnostics.js";

import { documentSource } from "./document.js";

export const compilerVersion = Malloy.version;
export type { Position } from "./metadata.js";
const sourceURL = new URL("memory://pymalloy/model.malloy");

export interface ParseOptions {
  url?: URL;
  position?: Position;
}

export interface SymbolInfo {
  name: string;
  type: string;
  range: Range;
  lens_range: Range;
  children: SymbolInfo[];
}

export interface ParseReport {
  url: string;
  diagnostics: Diagnostic[];
  symbols: SymbolInfo[];
  tables: Array<{ connection: string; path: string; range: Range }>;
  imports: ImportInfo[];
  completions: Array<{ type: string; text: string }>;
  help: { type: string; token: string | null } | null;
}

export function validatePosition(position: Position): void {
  if (
    !Number.isInteger(position.line) ||
    position.line < 0 ||
    !Number.isInteger(position.character) ||
    position.character < 0
  ) {
    throw new RangeError("Positions require nonnegative integer line and character values");
  }
}

export function parseSource(source: string, options: ParseOptions = {}): ParseReport {
  const url = options.url ?? sourceURL;
  if (options.position) validatePosition(options.position);
  let document;
  try {
    document = documentSource(source, url);
  } catch (error) {
    if (!(error instanceof ToolingError)) throw error;
    return {
      url: url.href,
      diagnostics: error.diagnostics,
      symbols: [],
      tables: [],
      imports: [],
      completions: [],
      help: null,
    };
  }
  const parsed = Malloy.parse({ source: document.source, url });
  const symbol = (value: (typeof parsed.symbols)[number]): SymbolInfo => ({
    name: value.name,
    type: value.type,
    range: value.range.toJSON(),
    lens_range: value.lensRange.toJSON(),
    children: value.children.map(symbol),
  });
  const symbols = parsed.symbols.map(symbol);
  const tables = parsed.tablePathInfo.map((table) => ({
    connection: table.connectionId,
    path: table.tablePath,
    range: table.range.toJSON(),
  }));
  const completions = options.position
    ? parsed.completions(options.position).map((value) => ({
        type: value.type,
        text: value.text,
      }))
    : [];
  const context = options.position ? parsed.helpContext(options.position) : undefined;
  const help = context ? { type: context.type, token: context.token ?? null } : null;
  const problems = diagnostics(parseProblems(parsed));
  for (const statement of document.statements ?? []) {
    if (statement.type !== "sql") continue;
    for (const embedded of statement.embeddedMalloyQueries) {
      const query = Malloy.parse({ source: `run: ${embedded.query}`, url });
      void query.symbols;
      problems.push(
        ...offsetDiagnostics(
          diagnostics(parseProblems(query)),
          { url: url.href, range: embedded.malloyRange },
          5,
        ),
      );
    }
  }
  return {
    url: url.href,
    diagnostics: problems,
    symbols,
    tables,
    imports: symbols
      .filter((value) => value.type === "import")
      .map((value) => ({
        url: new URL(value.name, url).href,
        location: { url: url.href, range: value.range },
      })),
    completions,
    help,
  };
}

export function formatSource(source: string) {
  const formatted = formatMalloy(source);
  const problems = formatted.errors.map((error) => ({
    code: "syntax-error",
    severity: "error" as const,
    message: error.message,
    location: {
      url: sourceURL.href,
      range: {
        start: { line: error.line - 1, character: error.column },
        end: { line: error.line - 1, character: error.column },
      },
    },
    replacement: null,
    error_tag: null,
    data: null,
  }));
  return { source: problems.length ? source : formatted.result, diagnostics: problems };
}
