import { execFileSync } from "node:child_process";
import { copyFile, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const assets = join(root, "packages/python/src/pymalloy/_assets");
await rm(assets, { recursive: true, force: true });
await mkdir(assets, { recursive: true });
for (const [name, source] of Object.entries({
  "server.mjs": "packages/server/dist/server.mjs",
  "widget.js": "packages/widget/dist/widget.js",
  "widget.css": "packages/widget/dist/widget.css",
})) {
  await copyFile(join(root, source), join(assets, name));
}

/** @type {Record<string, { paths: string[] }[]>} */
const licenses = JSON.parse(
  execFileSync("pnpm", ["licenses", "list", "--prod", "--json"], { cwd: root, encoding: "utf8" }),
);
const directories = [
  ...new Set(
    Object.values(licenses)
      .flat()
      .flatMap((pkg) => pkg.paths),
  ),
].sort();
const notices = [];
for (const directory of directories) {
  const pkg = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
  const names = (await readdir(directory))
    .filter((name) => /^(licen[cs]e|notice|copying)(\.|$)/i.test(name))
    .sort();
  const texts = await Promise.all(names.map((name) => readFile(join(directory, name), "utf8")));
  notices.push(`${pkg.name}@${pkg.version} (${pkg.license ?? "see notice"})\n${texts.join("\n")}`);
}
await writeFile(join(assets, "THIRD_PARTY_LICENSES.txt"), notices.join("\n\n---\n\n"));
console.log("Staged widget, server, and dependency notices");
