import { copyFile, cp, mkdir, rm } from "node:fs/promises";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const assets = join(root, "packages/python/src/pymalloy/_assets");
await rm(assets, { recursive: true, force: true });
await mkdir(assets, { recursive: true });
for (const [name, source] of Object.entries({
  "headless.mjs": "packages/headless/dist/headless.mjs",
  "headless.LICENSE.txt": "packages/headless/dist/headless.LICENSE.txt",
})) {
  await copyFile(join(root, source), join(assets, name));
}

await cp(join(root, "packages/widget/dist"), join(assets, "widget"), {
  recursive: true,
  filter: (path) => !path.endsWith(".map"),
});

const agent = join(assets, "agent");
await mkdir(agent);
await copyFile(join(root, "plugin.json"), join(agent, "plugin.json"));
await cp(join(root, "skills/pymalloy"), join(agent, "skills/pymalloy"), { recursive: true });
console.log("Staged widget, headless compiler, artifact notices, and agent guidance");
