import { defineConfig } from "vite-plus";

import { bundleNotices } from "../../tools/bundle-notices";

export default defineConfig({
  plugins: [bundleNotices("headless.LICENSE.txt")],
  define: { "process.env": "{}" },
  build: {
    target: "es2023",
    sourcemap: "hidden",
    ssr: "src/main.ts",
    minify: true,
    rollupOptions: {
      external: ["node:fs"],
      output: { entryFileNames: "headless.mjs", codeSplitting: false },
    },
  },
  ssr: { noExternal: true },
});
