import { antiSlopPluginRules } from "./index.ts";

export const antiSlopRules = Object.fromEntries(
  Object.keys(antiSlopPluginRules).map((name) => [
    `anti-slop/${name}`,
    "error" as const,
  ]),
);
