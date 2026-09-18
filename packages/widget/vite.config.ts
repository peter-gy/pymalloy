import { defineConfig } from "vite-plus";

export default defineConfig({
  test: { include: ["tests/**/*.test.ts"], testTimeout: 5000 },
  build: {
    target: "es2022",
    lib: {
      entry: "src/index.ts",
      formats: ["es"],
      fileName: () => "widget.js",
      cssFileName: "widget",
    },
    rollupOptions: { output: { codeSplitting: false } },
    sourcemap: false,
  },
});
