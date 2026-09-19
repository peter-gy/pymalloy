import { fileURLToPath } from "node:url";
import stylex from "@stylexjs/unplugin/vite";
import anywidgetBundle from "anywidget-bundle";
import { defineConfig } from "vite-plus";
import { bundleNotices } from "@pymalloy/scripts/bundle-notices";

export default defineConfig(({ mode }) => ({
  plugins:
    mode === "test"
      ? []
      : [
          stylex({
            useCSSLayers: true,
            unstable_moduleResolution: { type: "commonJS", rootDir: import.meta.dirname },
          }),
          anywidgetBundle({ app: "./src/index.ts", outDir: "./dist" }),
          bundleNotices("widget.LICENSE.txt"),
        ],
  resolve: {
    alias: {
      "@malloy-runtime/browser": fileURLToPath(new URL("../browser/src/index.ts", import.meta.url)),
    },
  },
  test: { include: ["tests/**/*.test.ts"], testTimeout: 5000 },
  build: {
    minify: true,
    target: "es2022",
    rollupOptions: {
      transform: { inject: { process: "process/browser" }, define: { global: "globalThis" } },
    },
  },
}));
