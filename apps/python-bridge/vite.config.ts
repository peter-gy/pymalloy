import { fileURLToPath } from "node:url";
import { defineConfig } from "vite-plus";

export default defineConfig({
  pack: {
    entry: ["src/main.ts"],
    alias: {
      "@pymalloy/core": fileURLToPath(new URL("../../packages/core/src/index.ts", import.meta.url)),
    },
    format: "esm",
    platform: "node",
    target: "node24",
    dts: false,
    sourcemap: false,
    deps: { alwaysBundle: [/.*/] },
    outExtensions: () => ({ js: ".mjs" }),
  },
});
