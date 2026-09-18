import { defineConfig } from "vite-plus";

export default defineConfig({
  pack: {
    entry: ["src/index.ts", "src/tooling.ts", "src/types.ts"],
    format: "esm",
    dts: true,
    platform: "neutral",
    target: "es2023",
    outExtensions: () => ({ js: ".mjs", dts: ".d.mts" }),
  },
  test: { include: ["tests/**/*.test.ts"], testTimeout: 30000 },
});
