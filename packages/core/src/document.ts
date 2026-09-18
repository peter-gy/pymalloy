import type { DocumentKind } from "./source";
import type { DocumentRange } from "@malloydata/malloy";
import { MalloySQLParser } from "@malloydata/malloy-sql";
import { diagnostics, ToolingError } from "./diagnostics";

export const RUN_PREFIX = "run: ";

export function documentSource(document: string, url: URL, kind: DocumentKind = "model") {
  if (kind === "model") return { source: document };
  const sourceLines = document.split(/\r?\n/);
  // The document parser counts UTF-16 units, while Malloy reports Unicode code points.
  const range = (value: DocumentRange): DocumentRange => {
    const point = (position: DocumentRange["start"]) => ({
      line: position.line,
      character: Array.from((sourceLines[position.line] ?? "").slice(0, position.character)).length,
    });
    return { start: point(value.start), end: point(value.end) };
  };
  const parsed = MalloySQLParser.parse(document, url.href);
  if (parsed.errors.length) {
    throw new ToolingError(
      parsed.errors.map((error) => error.message).join("\n"),
      parsed.errors.flatMap((error) =>
        diagnostics(error.problems).map((problem) => ({
          ...problem,
          location: problem.location
            ? { ...problem.location, range: range(problem.location.range) }
            : null,
        })),
      ),
    );
  }
  const lines = sourceLines.map(() => "");
  for (const statement of parsed.statements) {
    statement.range = range(statement.range);
    statement.delimiterRange = range(statement.delimiterRange);
    if (statement.type === "sql") {
      for (const embedded of statement.embeddedMalloyQueries) {
        embedded.range = range(embedded.range);
        embedded.malloyRange = range(embedded.malloyRange);
      }
    }
    if (statement.type === "malloy") {
      statement.text.split(/\r?\n/).forEach((line, i) => {
        lines[statement.range.start.line + i] = line;
      });
    }
  }
  return { source: lines.join("\n"), statements: parsed.statements };
}

export function sqlParts(
  statement: Extract<
    ReturnType<typeof MalloySQLParser.parse>["statements"][number],
    { type: "sql" }
  >,
): string[] {
  const characters = Array.from(statement.text);
  const lineOffsets = [0];
  for (const [index, character] of characters.entries()) {
    if (character === "\n") lineOffsets.push(index + 1);
  }
  const offset = (position: DocumentRange["start"]) => {
    const line = position.line - statement.range.start.line;
    return (
      lineOffsets[line] + position.character - (line === 0 ? statement.range.start.character : 0)
    );
  };
  const parts: string[] = [];
  let previous = 0;
  for (const embedded of statement.embeddedMalloyQueries) {
    parts.push(characters.slice(previous, offset(embedded.range.start)).join(""));
    previous = offset(embedded.range.end);
  }
  parts.push(characters.slice(previous).join(""));
  return parts;
}
