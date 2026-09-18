import { copyFile, cp, mkdir, rm } from "node:fs/promises";
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
  "widget.LICENSE.txt": "packages/widget/dist/widget.LICENSE.txt",
  "server.LICENSE.txt": "packages/server/dist/server.LICENSE.txt",
})) {
  await copyFile(join(root, source), join(assets, name));
}

const agent = join(assets, "agent");
await mkdir(agent);
await copyFile(join(root, "plugin.json"), join(agent, "plugin.json"));
await cp(join(root, "skills/pymalloy"), join(agent, "skills/pymalloy"), { recursive: true });
console.log("Staged widget, server, artifact notices, and agent guidance");
