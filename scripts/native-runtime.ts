import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export async function stageNativeRuntime(root: string, assets: string): Promise<void> {
  const python = join(root, "packages/python");
  const metadata: {
    packages: {
      name: string;
      version: string;
      manifest_path: string;
    }[];
  } = JSON.parse(
    execFileSync("cargo", ["metadata", "--format-version", "1", "--locked"], {
      cwd: python,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    }),
  );
  const packages = await Promise.all(
    ["deno_web", "deno_webidl"].map(async (name) => {
      const pkg = metadata.packages.find((pkg) => pkg.name === name);
      if (!pkg) throw new Error(`Missing native runtime package ${name}`);
      const directory = dirname(pkg.manifest_path);
      const files = (await readdir(directory, { withFileTypes: true }))
        .filter((entry) => entry.isFile() && /\.m?js$/.test(entry.name))
        .map((entry) => entry.name)
        .sort();
      if (files.length === 0) throw new Error(`Missing native runtime sources for ${name}`);
      const sources = Object.fromEntries(
        await Promise.all(
          files.map(async (file) => [
            `ext:${name}/${file}`,
            await readFile(join(directory, file), "utf8"),
          ]),
        ),
      );
      return { name, version: pkg.version, sources };
    }),
  );
  const runtime = JSON.stringify({ packages }) + "\n";
  await writeFile(join(assets, "native.runtime.json"), runtime);
  const manifest = {
    cargoLockSha256: createHash("sha256")
      .update(await readFile(join(python, "Cargo.lock")))
      .digest("hex"),
    runtimeSha256: createHash("sha256").update(runtime).digest("hex"),
  };
  await writeFile(join(assets, "native.manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
}
