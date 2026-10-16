import { defineConfig } from "vite-plus";

import { bundleNotices } from "@pymalloy/scripts/bundle-notices";
import { compilerBundle } from "@pymalloy/scripts/compiler-bundle";

export default defineConfig({
  plugins: [compilerBundle(), bundleNotices("compiler.LICENSE.txt")],
  define: { "process.env": "{}" },
  build: {
    target: "es2023",
    sourcemap: "hidden",
    minify: true,
    rollupOptions: {
      input: "src/entry.ts",
      output: { format: "iife", entryFileNames: "compiler.js", codeSplitting: false },
    },
  },
  test: { include: ["tests/**/*.test.ts"], testTimeout: 30000 },
});
