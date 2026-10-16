import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, realpath, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import type { Plugin } from "vite-plus";

interface CargoPackage {
  name: string;
  dependencies: { name: string; req: string }[];
  metadata: { pymalloy: { "bootstrap-revision": number } };
}

export function compilerBundle(): Plugin {
  const root = resolve(import.meta.dirname, "..");
  let malloyVersion: string;
  return {
    name: "compiler-bundle",
    async generateBundle(_options, bundle) {
      const chunks = Object.values(bundle).filter((output) => output.type === "chunk");
      if (chunks.length !== 1 || chunks[0].imports.length || chunks[0].dynamicImports.length)
        throw new Error("Compiler bundle must contain one closed JavaScript module graph");
      const malloy = new Map<string, string>();
      for (const id of Object.keys(chunks[0].modules)) {
        if (id.includes("__vite-browser-external"))
          throw new Error(`Compiler bundle requires an unavailable host module: ${id}`);
        if (!id.includes("node_modules/")) continue;
        let directory = dirname(id.replace(/^\0/, "").split("?")[0]);
        while (directory !== dirname(directory)) {
          try {
            const pkg: { name: string; version: string } = JSON.parse(
              await readFile(join(directory, "package.json"), "utf8"),
            );
            if (pkg.name === "@malloydata/malloy")
              malloy.set(await realpath(directory), pkg.version);
            break;
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
      if (malloy.size !== 1)
        throw new Error(`Compiler bundle contains ${malloy.size} Malloy module graphs`);
      malloyVersion = [...malloy.values()][0];
    },
    async writeBundle(options) {
      if (!options.dir) throw new Error("Compiler bundle requires an output directory");
      const metadata: { packages: CargoPackage[] } = JSON.parse(
        execFileSync(
          "cargo",
          [
            "metadata",
            "--manifest-path",
            join(root, "packages/python/Cargo.toml"),
            "--no-deps",
            "--format-version",
            "1",
          ],
          { encoding: "utf8", cwd: root },
        ),
      );
      const native = metadata.packages.find((pkg) => pkg.name === "pymalloy-native");
      if (!native) throw new Error("Compiler bundle requires the native package metadata");
      const version = (name: string): string => {
        const requirement = native.dependencies.find((dependency) => dependency.name === name)?.req;
        if (!requirement?.startsWith("="))
          throw new Error(`Compiler engine dependency ${name} must have an exact version`);
        return requirement.slice(1);
      };
      const sha256 = async (path: string): Promise<string> =>
        createHash("sha256")
          .update(await readFile(path))
          .digest("hex");
      const manifest = {
        bundleSha256: await sha256(join(options.dir, "compiler.js")),
        protocolSha256: await sha256(join(root, "packages/protocol/schema/protocol.json")),
        malloyVersion,
        patchSha256: await sha256(join(root, `patches/@malloydata__malloy@${malloyVersion}.patch`)),
        bootstrapRevision: native.metadata.pymalloy["bootstrap-revision"],
        engine: {
          denoCore: version("deno_core"),
          denoWeb: version("deno_web"),
          denoWebidl: version("deno_webidl"),
        },
      };
      await writeFile(
        join(options.dir, "compiler.manifest.json"),
        JSON.stringify(manifest, null, 2) + "\n",
      );
    },
  };
}
