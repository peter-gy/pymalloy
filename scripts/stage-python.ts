import { createHash } from "node:crypto";
import { copyFile, cp, mkdir, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { stageNativeRuntime } from "./native-runtime.ts";

const root = resolve(import.meta.dirname, "..");
const assets = join(root, "packages/python/src/pymalloy/_assets");
const compiler = join(root, "packages/compiler/dist");
const pyodide = join(root, "packages/pyodide/dist");
const manifest: {
  bundleSha256: string;
  protocolSha256: string;
  malloyVersion: string;
  patchSha256: string;
} = JSON.parse(await readFile(join(compiler, "compiler.manifest.json"), "utf8"));
const patch = `patches/@malloydata__malloy@${manifest.malloyVersion}.patch`;
const runtimeManifest: { bundleSha256: string; protocolSha256: string } = JSON.parse(
  await readFile(join(pyodide, "runtime.manifest.json"), "utf8"),
);
for (const [source, digest] of [
  ["packages/compiler/dist/compiler.js", manifest.bundleSha256],
  ["packages/protocol/schema/protocol.json", manifest.protocolSha256],
  [patch, manifest.patchSha256],
  ["packages/pyodide/dist/runtime.js", runtimeManifest.bundleSha256],
  ["packages/protocol/schema/protocol.json", runtimeManifest.protocolSha256],
]) {
  const actual = createHash("sha256")
    .update(await readFile(join(root, source)))
    .digest("hex");
  if (actual !== digest) throw new Error(`Compiler input ${source} changed. Run pnpm build.`);
}
await rm(assets, { recursive: true, force: true });
await mkdir(assets, { recursive: true });
await stageNativeRuntime(root, assets);
for (const [name, source] of Object.entries({
  "compiler.js": "packages/compiler/dist/compiler.js",
  "compiler.manifest.json": "packages/compiler/dist/compiler.manifest.json",
  "compiler.protocol.json": "packages/protocol/schema/protocol.json",
  "compiler.malloy.patch": patch,
})) {
  await copyFile(join(root, source), join(assets, name));
}

await cp(join(root, "packages/widget/dist"), join(assets, "widget"), {
  recursive: true,
  filter: (path) => !path.endsWith(".map"),
});
await cp(pyodide, join(assets, "pyodide"), {
  recursive: true,
  filter: (path) => !path.endsWith(".map"),
});

const agent = join(assets, "agent");
await mkdir(agent);
await copyFile(join(root, "plugin.json"), join(agent, "plugin.json"));
await cp(join(root, "skills/pymalloy"), join(agent, "skills/pymalloy"), { recursive: true });
console.log("Staged widget, embedded compiler, native runtime sources, and agent guidance");
