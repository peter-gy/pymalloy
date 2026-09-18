import { defineConfig } from "vite-plus";
import { antiSlopRules } from "./tools/oxlint/anti-slop/preset.ts";

const ignoredPaths = [
  "**/dist/**",
  "**/node_modules/**",
  "**/.vitepress/cache/**",
  "**/.vitepress/dist/**",
  "**/_assets/**",
  "**/playwright-report/**",
  "**/test-results/**",
  ".venv/**",
  "uv.lock",
  "pnpm-lock.yaml",
  "tools/oxlint/anti-slop/**",
];

export default defineConfig({
  fmt: { ignorePatterns: ignoredPaths },
  lint: {
    ignorePatterns: ignoredPaths,
    categories: { correctness: "error", perf: "error" },
    plugins: ["typescript", "unicorn", "import"],
    jsPlugins: [{ name: "anti-slop", specifier: "./tools/oxlint/anti-slop/index.ts" }],
    options: {
      denyWarnings: true,
      reportUnusedDisableDirectives: "error",
      typeAware: true,
    },
    rules: {
      ...antiSlopRules,
      "typescript/consistent-type-imports": "error",
      // Compilation, database calls, and authored document cells run in order.
      "no-await-in-loop": "off",
    },
    overrides: [
      {
        files: ["packages/core/src/diagnostics.ts"],
        // JavaScript can throw arbitrary values. This adapter decodes Malloy errors
        // and maps source URLs while preserving unrelated host exceptions.
        rules: {
          "anti-slop/no-unknown-parameters": "off",
          "anti-slop/no-runtime-typeof": "off",
        },
      },
      {
        files: [
          "packages/node/src/duckdb.ts",
          "packages/core/src/selection.ts",
          "packages/core/tests/syntax.test.ts",
          "packages/node/src/session.ts",
          "packages/browser/src/session.ts",
        ],
        rules: {
          "anti-slop/no-runtime-typeof": ["error", { allowInTypeGuards: true }],
        },
      },
      {
        files: ["packages/duckdb/src/arrow.ts"],
        // Arrow cells enter through their schema, which determines their runtime representation.
        rules: {
          "anti-slop/no-runtime-typeof": "off",
          "anti-slop/no-unknown-parameters": "off",
        },
      },
      {
        files: ["packages/duckdb/src/result.ts"],
        // Stable result serialization preserves exact scalars from the materialized Value union.
        rules: { "anti-slop/no-runtime-typeof": "off" },
      },
    ],
  },
});
