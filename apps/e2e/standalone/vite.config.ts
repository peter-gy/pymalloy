import { createReadStream, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isAbsolute, dirname, join } from "node:path";
import { defineConfig } from "vite-plus";

if (process.env.PYMALLOY_BROWSER_BUNDLE && !isAbsolute(process.env.PYMALLOY_BROWSER_BUNDLE))
  throw new Error("PYMALLOY_BROWSER_BUNDLE must be an absolute path");

const distribution = fileURLToPath(new URL("../../../dist/", import.meta.url));
const widgetRoot = new URL("../../../packages/widget/dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("anywidget.json", widgetRoot), "utf8"));
const runtimeFiles = new Map<string, URL>([
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
              request.url?.endsWith(".wasm") ? "application/wasm" : "text/javascript",
            );
            createReadStream(fileURLToPath(runtimeFile)).pipe(response);
            return;
          }
          const packageName = /^\/simple\/([^/]+)\/$/.exec(request.url ?? "")?.[1];
          const packageIndex = packageName === "pymalloy";
          if (packageName && !packageIndex) {
            response.writeHead(302, {
              Location: `https://pypi.org/simple/${encodeURIComponent(packageName)}/`,
            });
            response.end();
            return;
          }
          if (!packageIndex && !request.url?.startsWith("/wheels/")) return next();
          const wheels = readdirSync(distribution).filter((file) =>
            /^pymalloy-.*-py3-none-any\.whl$/.test(file),
          );
          if (wheels.length !== 1) {
            response.statusCode = 500;
            response.end("Build exactly one PyMalloy wheel before running browser tests.");
            return;
          }
          const wheel = wheels[0];
          if (packageIndex) {
            response.setHeader("Content-Type", "text/html");
            response.end(`<a href="/wheels/${wheel}">${wheel}</a>`);
          } else if (request.url === `/wheels/${wheel}`) {
            response.setHeader("Content-Type", "application/octet-stream");
            createReadStream(`${distribution}/${wheel}`).pipe(response);
          } else {
            response.statusCode = 404;
            response.end();
          }
        });
      },
    },
  ],
});
