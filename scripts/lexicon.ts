import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import type { ATN } from "antlr4ts/atn/ATN";
import type { ATNState } from "antlr4ts/atn/ATNState";
import type { CharStream } from "antlr4ts/CharStream";
import type { Lexer } from "antlr4ts/Lexer";
import { CharStreams } from "antlr4ts/CharStreams.js";
import { ATNStateType } from "antlr4ts/atn/ATNStateType.js";
import { RuleTransition } from "antlr4ts/atn/RuleTransition.js";

const require = createRequire(import.meta.url);
const directory = dirname(require.resolve("@malloydata/malloy/package.json"));
const { version }: { version: string } = require(join(directory, "package.json"));
const {
  MalloyLexer,
}: {
  MalloyLexer: {
    new (input: CharStream): Lexer;
    ruleNames: string[];
    _ATN: ATN;
    IDENTIFIER: number;
  };
} = require(join(directory, "dist/lang/lib/Malloy/MalloyLexer.js"));
const { KEYWORD_DISPLAY_NAMES }: { KEYWORD_DISPLAY_NAMES: Record<string, string> } = require(
  join(directory, "dist/lang/lib/Malloy/keyword-display-names.js"),
);
const memo = new Map<number, Set<string>>();
const active = new Set<number>();

// Enumerate the pinned lexer's finite keyword rules, including optional suffixes.
function spellings(state: ATNState): Set<string> {
  if (state.stateType === ATNStateType.RULE_STOP) return new Set([""]);
  const cached = memo.get(state.stateNumber);
  if (cached) return cached;
  if (active.has(state.stateNumber)) throw new Error("Malloy keyword rule is no longer finite");
  active.add(state.stateNumber);
  const words = new Set<string>();
  for (const transition of state.getTransitions()) {
    const followState = transition instanceof RuleTransition ? transition.followState : undefined;
    const prefixes = followState
      ? spellings(transition.target)
      : transition.isEpsilon
        ? [""]
        : transition.label!.toArray().map((code) => String.fromCodePoint(code).toLowerCase());
    const suffixes = spellings(followState ?? transition.target);
    for (const prefix of prefixes) for (const suffix of suffixes) words.add(prefix + suffix);
  }
  active.delete(state.stateNumber);
  memo.set(state.stateNumber, words);
  return words;
}

/** Project reserved words from the pinned Malloy lexer into a Python module. */
export function generateLexicon(): string {
  const words = new Set<string>();
  for (const [name, display] of Object.entries(KEYWORD_DISPLAY_NAMES)) {
    if (display.endsWith(":")) continue;
    const rule = MalloyLexer.ruleNames.indexOf(name);
    if (rule < 0) throw new Error(`Malloy keyword ${name} has no lexer rule`);
    for (const word of spellings(MalloyLexer._ATN.ruleToStartState[rule])) {
      const tokens = new MalloyLexer(CharStreams.fromString(word)).getAllTokens();
      if (
        tokens.length !== 1 ||
        tokens[0].type === MalloyLexer.IDENTIFIER ||
        tokens[0].text !== word
      )
        throw new Error(`Malloy keyword ${word} does not lex as one reserved word`);
      words.add(word);
    }
  }
  return `"""Generated from Malloy ${version}'s native lexer. Run pnpm records to update."""\n\nRESERVED_WORDS = frozenset(\n    {\n${[
    ...words,
  ]
    .sort((left, right) => left.localeCompare(right, "en"))
    .map((word) => `        ${JSON.stringify(word)},\n`)
    .join("")}    }\n)\n`;
}
