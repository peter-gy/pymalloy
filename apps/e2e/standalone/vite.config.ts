import { createReadStream, readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isAbsolute, basename, dirname, join, resolve } from "node:path";
import { defineConfig } from "vite-plus";

if (process.env.PYMALLOY_BROWSER_BUNDLE && !isAbsolute(process.env.PYMALLOY_BROWSER_BUNDLE))
  throw new Error("PYMALLOY_BROWSER_BUNDLE must be an absolute path");
if (process.env.PYMALLOY_BROWSER_WHEEL && !isAbsolute(process.env.PYMALLOY_BROWSER_WHEEL))
  throw new Error("PYMALLOY_BROWSER_WHEEL must be an absolute path");

const distribution = fileURLToPath(new URL("../../../dist/browser/", import.meta.url));
function browserWheel() {
  const wheelFiles = process.env.PYMALLOY_BROWSER_WHEEL
    ? [resolve(process.env.PYMALLOY_BROWSER_WHEEL)]
    : readdirSync(distribution)
        .filter((file) => /^pymalloy-.*-py3-none-any\.whl$/.test(file))
        .map((file) => join(distribution, file));
  if (wheelFiles.length !== 1 || !wheelFiles[0].endsWith("-py3-none-any.whl"))
    throw new Error("Select exactly one browser wheel with PYMALLOY_BROWSER_WHEEL or dist/browser");
  return wheelFiles[0];
}
const widgetRoot = new URL("../../../packages/widget/dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("anywidget.json", widgetRoot), "utf8"));
const pythonMatrix: { runtimes: Record<string, { lockFile: string }> } = JSON.parse(
  readFileSync(new URL("../pyodide/runtime.json", import.meta.url), "utf8"),
);
const runtimeFiles = new Map<string, URL>([
  ...[
    "runtime.json",
    ...Object.values(pythonMatrix.runtimes).map((runtime) => runtime.lockFile),
  ].map((name) => [`/pyodide/${name}`, new URL(`../pyodide/${name}`, import.meta.url)] as const),
  ...manifest.modules.map(
    (path: string) => [`/widget/${path}`, new URL(path, widgetRoot)] as const,
  ),
  ...(process.env.PYMALLOY_BROWSER_BUNDLE
    ? [["/runtime.mjs", pathToFileURL(process.env.PYMALLOY_BROWSER_BUNDLE)] as const]
    : []),
  ...[
    "duckdb-mvp.wasm",
    "duckdb-browser-mvp.worker.js",
    "duckdb-eh.wasm",
    "duckdb-browser-eh.worker.js",
  ].map(
    (name) =>
      [
        `/duckdb/${name}`,
        new URL(
          `../../../packages/browser/node_modules/@duckdb/duckdb-wasm/dist/${name}`,
          import.meta.url,
        ),
      ] as const,
  ),
]);

export default defineConfig({
  cacheDir: process.env.PYMALLOY_BROWSER_BUNDLE
    ? join(dirname(process.env.PYMALLOY_BROWSER_BUNDLE), ".vite")
    : undefined,
  define: { "process.env": "{}", global: "globalThis" },
  root: fileURLToPath(new URL(".", import.meta.url)),
  server: { host: "127.0.0.1", port: 28443, strictPort: true },
  plugins: [
    {
      name: "python-package-index",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          response.setHeader("Access-Control-Allow-Origin", "*");
          if (request.url === "/runtime.mjs" && !process.env.PYMALLOY_BROWSER_BUNDLE) {
            response.writeHead(302, {
              Location: `/@fs/${fileURLToPath(new URL("../../../packages/browser/dist/index.mjs", import.meta.url))}`,
            });
            response.end();
            return;
          }
          const runtimeFile = runtimeFiles.get(request.url ?? "");
          if (runtimeFile) {
            response.setHeader(
              "Content-Type",
              request.url?.endsWith(".wasm")
                ? "application/wasm"
                : request.url?.endsWith(".json")
                  ? "application/json"
                  : "text/javascript",
            );
            createReadStream(fileURLToPath(runtimeFile)).pipe(response);
            return;
          }
          if (!request.url?.startsWith("/wheels/") && request.url !== "/browser-wheel.json")
            return next();
          const wheelFile = browserWheel();
          const wheel = basename(wheelFile);
          if (request.url === "/browser-wheel.json") {
            response.setHeader("Content-Type", "application/json");
            response.end(
              JSON.stringify({
                url: `/wheels/${wheel}`,
                sha256: createHash("sha256").update(readFileSync(wheelFile)).digest("hex"),
              }),
            );
            return;
          }
          if (request.url === `/wheels/${wheel}`) {
            response.setHeader("Content-Type", "application/octet-stream");
            createReadStream(wheelFile).pipe(response);
          } else {
            response.statusCode = 404;
            response.end();
          }
        });
      },
    },
  ],
});
