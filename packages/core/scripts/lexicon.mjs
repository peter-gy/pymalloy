import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { writeFileSync } from "node:fs";

const require = createRequire(new URL("../package.json", import.meta.url));
const directory = dirname(require.resolve("@malloydata/malloy/package.json"));
const { version } = require(join(directory, "package.json"));
const { MalloyLexer } = require(join(directory, "dist/lang/lib/Malloy/MalloyLexer.js"));
const { KEYWORD_DISPLAY_NAMES } = require(
  join(directory, "dist/lang/lib/Malloy/keyword-display-names.js"),
);
const { CharStreams } = require("antlr4ts/CharStreams");
const { ATNStateType } = require("antlr4ts/atn/ATNStateType");
const memo = new Map();
const active = new Set();

// Enumerate the pinned lexer's finite keyword rules, including optional suffixes.
function spellings(state) {
  if (state.stateType === ATNStateType.RULE_STOP) return new Set([""]);
  if (memo.has(state.stateNumber)) return memo.get(state.stateNumber);
  if (active.has(state.stateNumber)) throw new Error("Malloy keyword rule is no longer finite");
  active.add(state.stateNumber);
  const words = new Set();
  for (const transition of state.transitions) {
    const prefixes = transition.followState
      ? spellings(transition.target)
      : transition.isEpsilon
        ? [""]
        : transition.label.toArray().map((code) => String.fromCodePoint(code).toLowerCase());
    const suffixes = spellings(transition.followState ?? transition.target);
    for (const prefix of prefixes) for (const suffix of suffixes) words.add(prefix + suffix);
  }
  active.delete(state.stateNumber);
  memo.set(state.stateNumber, words);
  return words;
}

const words = new Set();
for (const [name, display] of Object.entries(KEYWORD_DISPLAY_NAMES)) {
  if (display.endsWith(":")) continue;
  const rule = MalloyLexer.ruleNames.indexOf(name);
  if (rule < 0) throw new Error(`Malloy keyword ${name} has no lexer rule`);
  for (const word of spellings(MalloyLexer._ATN.ruleToStartState[rule])) {
    const tokens = new MalloyLexer(CharStreams.fromString(word)).getAllTokens();
    if (tokens.length !== 1 || tokens[0].type === MalloyLexer.IDENTIFIER || tokens[0].text !== word)
      throw new Error(`Malloy keyword ${word} does not lex as one reserved word`);
    words.add(word);
  }
}
const source = `"""Generated from Malloy ${version}'s native lexer. Run pnpm records to update."""\n\nRESERVED_WORDS = frozenset({\n${[
  ...words,
]
  .sort((left, right) => left.localeCompare(right, "en"))
  .map((word) => `    ${JSON.stringify(word)},\n`)
  .join("")}})\n`;
writeFileSync(new URL("../../python/src/pymalloy/_lexicon.py", import.meta.url), source);
