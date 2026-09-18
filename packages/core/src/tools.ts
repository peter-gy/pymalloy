import { tableReferences } from "./tables";
import { Malloy, MalloyTranslator, Parse } from "@malloydata/malloy";
import type { ParserRuleContext } from "antlr4ts";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";
import type { ParseTreeListener } from "antlr4ts/tree/ParseTreeListener.js";
import { formatMalloy } from "./upstream";
import type { SourcePosition, SourceRange, ImportInfo } from "./metadata";
import { diagnostics, ToolingError, offsetDiagnostics, type Diagnostic } from "./diagnostics";

import { documentSource } from "./document";

export const compilerVersion = Malloy.version;
export type { SourcePosition } from "./metadata";
const sourceURL = new URL("memory://pymalloy/model.malloy");

/** @title ParseOptions */
export interface ParseOptions {
  url?: URL;
  position?: SourcePosition;
}

/** @title SymbolInfo */
export interface SymbolInfo {
  name: string;
  type: string;
  range: SourceRange;
  lensRange: SourceRange;
  children: SymbolInfo[];
}

/** @title ParseReport */
export interface ParseReport {
  url: string;
  compilerVersion: string;
  diagnostics: Diagnostic[];
  symbols: SymbolInfo[];
  tables: Array<{ connection: string; path: string; range: SourceRange }>;
  imports: ParsedImport[];
  completions: Array<{ type: string; text: string }>;
  help: { type: string; token: string | null } | null;
}

/** The compiler-selected string literal, including delimiters, in Unicode codepoints. */
export interface ParsedImport extends ImportInfo {
  reference: SourceSpan;
}

export interface SourceSpan {
  /** @asType integer @minimum 0 */
  start: number;
  /** @asType integer @minimum 0 */
  end: number;
}

export function validatePosition(position: SourcePosition): void {
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
      compilerVersion,
      diagnostics: error.diagnostics,
      symbols: [],
      tables: [],
      imports: [],
      completions: [],
      help: null,
    };
  }
  const translator = new MalloyTranslator(url.href, url.href, {
    urls: { [url.href]: document.source },
  });
  const parsed = new Parse(translator);
  const symbol = (value: (typeof parsed.symbols)[number]): SymbolInfo => ({
    name: value.name,
    type: value.type,
    range: value.range.toJSON(),
    lensRange: value.lensRange.toJSON(),
    children: value.children.map(symbol),
  });
  const symbols = parsed.symbols.map(symbol);
  const tables = tableReferences(translator).map(({ connection, path, range }) => ({
    connection,
    path,
    range,
  }));
  const completions = options.position
    ? parsed.completions(options.position).map((value) => ({
        type: value.type,
        text: value.text,
      }))
    : [];
  const context = options.position ? parsed.helpContext(options.position) : undefined;
  const help = context ? { type: context.type, token: context.token ?? null } : null;
  const problems = diagnostics(translator.problems());
  const imports = symbols.filter((value) => value.type === "import");
  const importStarts = new Set(
    imports.map((value) => `${value.range.start.line}:${value.range.start.character}`),
  );
  const importReferences = new Map<string, ParsedImport["reference"]>();
  const syntax = translator.parseStep.step(translator).parse;
  if (syntax && imports.length) {
    const authoredOffsets = [0];
    let offset = 0;
    for (const character of source) {
      offset += 1;
      if (character === "\n") authoredOffsets.push(offset);
    }
    const listener: ParseTreeListener & {
      enterImportStatement(context: ParserRuleContext & { importURL(): ParserRuleContext }): void;
    } = {
      enterImportStatement: (context: ParserRuleContext & { importURL(): ParserRuleContext }) => {
        const start = `${context.start.line - 1}:${context.start.charPositionInLine}`;
        if (!importStarts.has(start)) return;
        const target = context.importURL();
        const last = target.stop!;
        const endLines = (last.text ?? "").split("\n");
        const endLine = last.line - 1 + endLines.length - 1;
        const endColumn =
          (endLines.length === 1 ? last.charPositionInLine : 0) +
          Array.from(endLines[endLines.length - 1]).length;
        importReferences.set(start, {
          start: authoredOffsets[target.start.line - 1] + target.start.charPositionInLine,
          end: authoredOffsets[endLine] + endColumn,
        });
      },
    };
    ParseTreeWalker.DEFAULT.walk(listener, syntax.root);
  }
  for (const statement of document.statements ?? []) {
    if (statement.type !== "sql") continue;
    for (const embedded of statement.embeddedMalloyQueries) {
      const child = new MalloyTranslator(url.href, url.href, {
        urls: { [url.href]: `run: ${embedded.query}` },
      });
      const query = new Parse(child);
      void query.symbols;
      problems.push(
        ...offsetDiagnostics(
          diagnostics(child.problems()),
          { url: url.href, range: embedded.malloyRange },
          5,
        ),
      );
    }
  }
  return {
    url: url.href,
    compilerVersion,
    diagnostics: problems,
    symbols,
    tables,
    imports: imports.map((value) => {
      const reference = importReferences.get(
        `${value.range.start.line}:${value.range.start.character}`,
      );
      if (!reference) throw new Error("Malloy import has no source reference");
      return {
        url: new URL(value.name, url).href,
        location: { url: url.href, range: value.range },
        reference,
      };
    }),
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
    errorTag: null,
    data: null,
  }));
  return { source: problems.length ? source : formatted.result, diagnostics: problems };
}
