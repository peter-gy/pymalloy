import { defineConfig } from "vite-plus";

export default defineConfig({
  test: { include: ["tests/**/*.test.ts"] },
  pack: {
    entry: ["src/index.ts"],
    format: "esm",
    dts: true,
    platform: "browser",
    target: "es2023",
    minify: true,
    inputOptions: {
      transform: { inject: { process: "process/browser" }, define: { global: "globalThis" } },
    },
    outExtensions: () => ({ js: ".mjs", dts: ".d.mts" }),
  },
});
