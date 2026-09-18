import { type MalloyTranslator } from "@malloydata/malloy";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";
import type { SourceRange } from "./metadata";
import { createParse, parseTree, type NativeListener } from "./upstream";

interface TableReference {
  connection: string;
  path: string;
  range: SourceRange;
  start: number;
  end: number;
}

/** Native decoding paired with ANTLR offsets; upstream end ranges mix UTF-16 and codepoints. */
export function tableReferences(translator: MalloyTranslator): TableReference[] {
  const parsed = parseTree(translator);
  if (!parsed) return [];
  const metadata = new Map(
    createParse(translator).tablePathInfo.map((table) => {
      const start = table.range.toJSON().start;
      return [`${start.line}:${start.character}`, table];
    }),
  );
  if (!metadata.size) return [];
  const tables: TableReference[] = [];
  const listener: NativeListener = {
    enterExploreTable(context) {
      const first = context.start;
      const last = context.stop!;
      const table = metadata.get(`${first.line - 1}:${first.charPositionInLine}`);
      if (!table) return;
      tables.push({
        connection: table.connectionId,
        path: table.tablePath,
        start: first.startIndex,
        end: last.stopIndex + 1,
        range: {
          start: { line: first.line - 1, character: first.charPositionInLine },
          end: { line: last.line - 1, character: last.charPositionInLine + 1 },
        },
      });
    },
  };
  ParseTreeWalker.DEFAULT.walk(listener, parsed.root);
  return tables;
}
