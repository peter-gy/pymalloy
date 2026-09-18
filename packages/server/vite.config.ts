import { defineConfig } from "vite-plus";

export default defineConfig({
  define: { "process.env": "{}" },
  build: {
    target: "es2023",
    ssr: "src/main.ts",
    minify: true,
    rollupOptions: {
      external: ["node:fs"],
      output: { entryFileNames: "server.mjs", codeSplitting: false },
    },
  },
  ssr: { noExternal: true },
});
