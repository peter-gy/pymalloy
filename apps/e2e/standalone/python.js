export async function python() {
  const matrix = await fetch("/pyodide/runtime.json").then((response) => response.json());
  const runtime = matrix.runtimes[matrix.hosts.standalone];
  const lock = await fetch(`/pyodide/${runtime.lockFile}`).then((response) => response.json());
  const { loadPyodide } = await import(/* @vite-ignore */ `${runtime.indexURL}pyodide.mjs`);
  const pyodide = await loadPyodide({
    indexURL: runtime.indexURL,
    packageBaseUrl: runtime.indexURL,
    lockFileContents: lock,
  });
  await pyodide.loadPackage(Object.keys(lock.packages), { checkIntegrity: true });
  const wheel = await fetch("/browser-wheel.json").then((response) => response.json());
  const bytes = await fetch(wheel.url).then((response) => response.arrayBuffer());
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  if (digest !== wheel.sha256) throw new Error("Browser wheel SHA-256 mismatch");
  const filename = "/tmp/" + new URL(wheel.url, location.href).pathname.split("/").at(-1);
  pyodide.FS.writeFile(filename, new Uint8Array(bytes));
  pyodide.globals.set("wheel_url", "emfs:" + filename);
  try {
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(wheel_url, deps=False)
`);
  } finally {
    pyodide.FS.unlink(filename);
  }
  return pyodide;
}
