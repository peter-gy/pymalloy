import { defineConfig } from "vite-plus";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { compilerVersion } from "@malloy-runtime/compiler/tooling";
import { bundleNotices } from "@pymalloy/scripts/bundle-notices";

export default defineConfig({
  plugins: [
    {
      name: "pyodide-runtime-bundle",
      generateBundle(_options, bundle) {
        const chunks = Object.values(bundle).filter((output) => output.type === "chunk");
        if (chunks.length !== 1 || chunks[0].imports.length || chunks[0].dynamicImports.length)
          throw new Error("Pyodide runtime requires one closed JavaScript module graph");
        for (const id of Object.keys(chunks[0].modules)) {
          if (id.includes("__vite-browser-external"))
            throw new Error(`Pyodide runtime requires an unavailable host module: ${id}`);
        }
      },
      async writeBundle(options) {
        if (!options.dir) throw new Error("Pyodide runtime requires an output directory");
        const sha256 = async (path: string | URL): Promise<string> =>
          createHash("sha256")
            .update(await readFile(path))
            .digest("hex");
        const manifest = {
          bundleSha256: await sha256(join(options.dir, "runtime.js")),
          protocolSha256: await sha256(
            new URL("../protocol/schema/protocol.json", import.meta.url),
          ),
          malloyVersion: compilerVersion,
        };
        await writeFile(
          join(options.dir, "runtime.manifest.json"),
          JSON.stringify(manifest, null, 2) + "\n",
        );
      },
    },
    bundleNotices("runtime.LICENSE.txt"),
  ],
  build: {
    target: "es2023",
    sourcemap: "hidden",
    minify: true,
    rollupOptions: {
      input: "src/entry.ts",
      output: { format: "iife", entryFileNames: "runtime.js", codeSplitting: false },
      transform: { inject: { process: "process/browser" }, define: { global: "globalThis" } },
    },
  },
  test: { include: ["tests/**/*.test.ts"], testTimeout: 30000 },
});
