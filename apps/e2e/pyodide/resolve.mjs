import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const work = pathToFileURL(resolve(process.argv[2]) + "/");
const { loadPyodide } = await import(new URL("pyodide.mjs", work).href);
const runtime = JSON.parse(readFileSync(new URL("runtime.json", work), "utf8"));
const pyodide = await loadPyodide({
  indexURL: work.pathname,
  packageBaseUrl: runtime.indexURL,
  packageCacheDir: new URL("packages/", work).pathname,
});
if (pyodide.version !== runtime.version) throw new Error("Pyodide runtime version mismatch");
const pythonVersion = pyodide.runPython("import platform; platform.python_version()");
if (pythonVersion !== runtime.pythonVersion) {
  throw new Error(`Expected Python ${runtime.pythonVersion}, received ${pythonVersion}`);
}
console.log(`Pyodide ${pyodide.version} runs Python ${pythonVersion}`);
await pyodide.loadPackage("micropip");
pyodide.globals.set("requirements_json", JSON.stringify(runtime.requirements));
const lock = JSON.parse(
  await pyodide.runPythonAsync(`
import json, micropip
requirements = json.loads(requirements_json)
await micropip.install([f"{name}=={version}" for name, version in requirements.items()])
micropip.freeze()
`),
);
lock.info.python = pythonVersion;
const base = JSON.parse(readFileSync(new URL("pyodide-lock.json", work), "utf8"));
const selected = {};
const pending = [...Object.keys(runtime.requirements), "micropip"];
while (pending.length) {
  const name = pending
    .pop()
    .toLowerCase()
    .replaceAll(/[-_.]+/g, "-");
  if (selected[name]) continue;
  if (!lock.packages[name]) throw new Error(`Unresolved dependency: ${name}`);
  const value = structuredClone(lock.packages[name]);
  const upstream = base.packages[name];
  if (upstream && upstream.version === value.version) {
    value.file_name = new URL(upstream.file_name, runtime.indexURL).href;
  }
  value.depends = value.depends.map((dependency) =>
    dependency.toLowerCase().replaceAll(/[-_.]+/g, "-"),
  );
  value.depends.sort();
  selected[name] = value;
  pending.push(...value.depends);
}
lock.packages = Object.fromEntries(Object.entries(selected).sort(([a], [b]) => a.localeCompare(b)));
writeFileSync(new URL("pylock.json", work), JSON.stringify(lock, null, 2) + "\n");
