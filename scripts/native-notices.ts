import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

interface LicenseSource {
  name: string;
  url: string;
  encoding: "utf8" | "base64";
  sha256: string;
}

const sha256 = (bytes: Buffer | string): string => createHash("sha256").update(bytes).digest("hex");

export async function nativeNotices(root: string, output: string): Promise<void> {
  const python = join(root, "packages/python");
  const metadata: {
    packages: {
      name: string;
      version: string;
      manifest_path: string;
      metadata: { pymalloy?: { "rust-tools": { "cargo-about": string } } };
    }[];
  } = JSON.parse(
    execFileSync("cargo", ["metadata", "--format-version", "1", "--locked"], {
      cwd: python,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    }),
  );
  const version = metadata.packages.find((pkg) => pkg.name === "pymalloy-native")?.metadata
    .pymalloy?.["rust-tools"]["cargo-about"];
  const tool = execFileSync("cargo-about", ["--version"], { encoding: "utf8" }).trim();
  if (!version || tool !== `cargo-about ${version}`)
    throw new Error("Install pinned Rust tools with python packages/python/rust_tools.py setup");
  const pinned: { v8Version: string; rustyV8Revision: string; sources: LicenseSource[] } =
    JSON.parse(await readFile(join(python, "native-licenses.json"), "utf8"));
  const v8 = metadata.packages.filter((pkg) => pkg.name === "v8");
  if (v8.length !== 1 || v8[0].version !== pinned.v8Version)
    throw new Error("Update native-licenses.json for the locked V8 version");
  const vcs: { git: { sha1: string } } = JSON.parse(
    await readFile(join(dirname(v8[0].manifest_path), ".cargo_vcs_info.json"), "utf8"),
  );
  if (vcs.git.sha1 !== pinned.rustyV8Revision)
    throw new Error("Native license sources differ from the locked V8 source revision");
  const rust = execFileSync(
    "cargo",
    ["about", "generate", "--locked", "--fail", "--config", "about.toml", "about.hbs"],
    { cwd: python, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
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
  await writeFile(join(dirname(output), "native.runtime.json"), runtime);
  const external = await Promise.all(
    pinned.sources.map(async (source) => {
      const response = await fetch(source.url, { signal: AbortSignal.timeout(30_000) });
      if (!response.ok)
        throw new Error(`Cannot load native license ${source.url}: ${response.status}`);
      const bytes =
        source.encoding === "base64"
          ? Buffer.from(await response.text(), "base64")
          : Buffer.from(await response.arrayBuffer());
      if (sha256(bytes) !== source.sha256)
        throw new Error(`Native license source changed: ${source.url}`);
      return `${source.name}\n${source.url}\n\n${bytes.toString("utf8")}\n`;
    }),
  );
  const notices = `${rust}\n${external.join("\n")}\n`;
  await writeFile(output, notices);
  const manifest = {
    cargoLockSha256: sha256(await readFile(join(python, "Cargo.lock"))),
    sourcesSha256: sha256(await readFile(join(python, "native-licenses.json"))),
    configSha256: sha256(await readFile(join(python, "about.toml"))),
    templateSha256: sha256(await readFile(join(python, "about.hbs"))),
    noticesSha256: sha256(notices),
    runtimeSha256: sha256(runtime),
  };
  await writeFile(
    join(dirname(output), "native.manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );
}
