import { createHighlighterCoreSync } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
import sql from "shiki/langs/sql.mjs";
import githubLight from "shiki/themes/github-light-default.mjs";
import githubDark from "shiki/themes/github-dark-default.mjs";
import type { LanguageRegistration } from "shiki/types";
import malloyGrammar from "@malloydata/syntax-highlight/grammars/malloy/malloy.tmGrammar.json?raw";
import motlyGrammar from "@malloydata/motly-ts-parser/grammar/source.motly.tmGrammar.json?raw";

const malloy: LanguageRegistration = {
  ...JSON.parse(malloyGrammar),
  name: "malloy",
  embeddedLangs: ["sql", "motly"],
};
const motly: LanguageRegistration = { ...JSON.parse(motlyGrammar), name: "motly" };

// One registry per widget module, loaded only when a code panel is displayed.
const highlighter = createHighlighterCoreSync({
  langs: [malloy, motly, sql],
  themes: [githubLight, githubDark],
  engine: createJavaScriptRegexEngine(),
});

export function highlight(source: string, language: "malloy" | "sql") {
  return highlighter
    .codeToTokensWithThemes(source, {
      lang: language,
      themes: { light: "github-light-default", dark: "github-dark-default" },
    })
    .flat()
    .filter((token) => token.content.length > 0);
}
