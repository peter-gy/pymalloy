import { Parse, type MalloyTranslator } from "@malloydata/malloy";
import type { ParserRuleContext } from "antlr4ts";
import type { ParseTreeListener } from "antlr4ts/tree/ParseTreeListener.js";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";
import type { SourceRange } from "./metadata.js";

interface TableReference {
  connection: string;
  path: string;
  range: SourceRange;
  start: number;
  end: number;
}

/** Native decoding paired with ANTLR offsets; upstream end ranges mix UTF-16 and codepoints. */
export function tableReferences(translator: MalloyTranslator): TableReference[] {
  const parsed = translator.parseStep.step(translator).parse;
  if (!parsed) return [];
  const metadata = new Map(
    new Parse(translator).tablePathInfo.map((table) => {
      const start = table.range.toJSON().start;
      return [`${start.line}:${start.character}`, table];
    }),
  );
  const tables: TableReference[] = [];
  const listener: ParseTreeListener & { enterExploreTable(context: ParserRuleContext): void } = {
    enterExploreTable(context: ParserRuleContext) {
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
