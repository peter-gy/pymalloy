import type { Plugin } from "vite-plus";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

const upstreamNotices = new Map([
  ["@stylexjs/stylex@0.19.1", new URL("./licenses/stylex-0.19.1.LICENSE", import.meta.url)],
  [
    "@duckdb/duckdb-wasm@1.33.1-dev57.0",
    new URL("./licenses/duckdb-wasm-1.33.1-dev57.0.LICENSE", import.meta.url),
  ],
  [
    "@malloydata/motly-ts-parser@0.9.0",
    new URL("./licenses/motly-ts-parser-0.9.0.LICENSE", import.meta.url),
  ],
]);

/** Collect notices only for packages whose modules occur in this artifact. */
export function bundleNotices(filename: string): Plugin {
  let text = "";
  return {
    name: "bundle-notices",
    async generateBundle(_options, bundle) {
      const packages = new Map<
        string,
        { directory: string; pkg: { name: string; version: string; license?: string } }
      >();
      for (const output of Object.values(bundle)) {
        if (output.type !== "chunk") continue;
        for (const [id, module] of Object.entries(output.modules)) {
          if (!id.includes("node_modules/") || module.renderedLength === 0) continue;
          let directory = dirname(id.replace(/^\0/, "").split("?")[0]);
          while (directory !== dirname(directory)) {
            try {
              const pkg = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
              if (pkg.name && pkg.version) {
                packages.set(`${pkg.name}@${pkg.version}`, { directory, pkg });
                break;
              }
            } catch (error) {
              if (
                !(
                  error instanceof Error &&
                  "code" in error &&
                  (error.code === "ENOENT" || error.code === "ENOTDIR")
                )
              )
                throw error;
            }
            directory = dirname(directory);
          }
        }
      }
      const notices = [];
      for (const [identity, { directory, pkg }] of [...packages].sort(([a], [b]) =>
        a < b ? -1 : a > b ? 1 : 0,
      )) {
        const names = (await readdir(directory))
          .filter((name) => /^(licen[cs]e|notice|copying)([._-]|$)/i.test(name))
          .sort();
        const texts = await Promise.all(
          names.map((name) => readFile(resolve(directory, name), "utf8")),
        );
        if (!texts.some((text) => text.trim())) {
          const upstream = upstreamNotices.get(identity);
          if (!upstream) throw new Error(`Missing license text for bundled dependency ${identity}`);
          texts.push(await readFile(upstream, "utf8"));
        }
        if (!texts.some((text) => text.trim()))
          throw new Error(`Empty license text for ${identity}`);
        notices.push(`${identity} (${pkg.license ?? "see notice"})\n${texts.join("\n")}`);
      }
      text = notices.join("\n\n---\n\n");
    },
    async writeBundle(options) {
      const directory = options.dir ?? (options.file ? dirname(options.file) : undefined);
      if (!directory) throw new Error("Dependency notices require an output directory");
      await writeFile(join(directory, filename), text);
    },
  };
}
