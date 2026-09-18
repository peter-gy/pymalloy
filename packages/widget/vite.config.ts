import { fileURLToPath } from "node:url";
import { defineConfig } from "vite-plus";

export default defineConfig({
  resolve: {
    alias: {
      "@malloy-runtime/browser": fileURLToPath(new URL("../browser/src/index.ts", import.meta.url)),
    },
  },
  test: { include: ["tests/**/*.test.ts"], testTimeout: 5000 },
  build: {
    minify: true,
    target: "es2022",
    cssCodeSplit: false,
    rollupOptions: {
      input: "src/index.ts",
      preserveEntrySignatures: "strict",
      transform: { inject: { process: "process/browser" }, define: { global: "globalThis" } },
      output: {
        format: "es",
        entryFileNames: "widget.js",
        assetFileNames: "widget.[ext]",
        codeSplitting: false,
      },
    },
    sourcemap: false,
  },
});
