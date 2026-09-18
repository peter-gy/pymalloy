import { createReadStream, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite-plus";

const distribution = fileURLToPath(new URL("../../../dist/", import.meta.url));
const runtimeFiles = new Map([
  [
    "/runtime.mjs",
    new URL(
      process.env.PYMALLOY_CONSUMER_CANARY
        ? "../../../nogit/consumer-canary/browser.mjs"
        : "../../../packages/browser/dist/index.mjs",
      import.meta.url,
    ),
  ],
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
  root: fileURLToPath(new URL(".", import.meta.url)),
  server: { host: "127.0.0.1", port: 28443, strictPort: true },
  plugins: [
    {
      name: "python-wheel",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const runtimeFile = runtimeFiles.get(request.url ?? "");
          if (runtimeFile) {
            response.setHeader(
              "Content-Type",
              request.url?.endsWith(".wasm") ? "application/wasm" : "text/javascript",
            );
            createReadStream(fileURLToPath(runtimeFile)).pipe(response);
            return;
          }
          if (request.url !== "/wheel.json" && !request.url?.startsWith("/wheels/")) return next();
          const wheels = readdirSync(distribution).filter((file) =>
            /^pymalloy-.*-py3-none-any\.whl$/.test(file),
          );
          if (wheels.length !== 1) {
            response.statusCode = 500;
            response.end("Build exactly one PyMalloy wheel before running browser tests.");
            return;
          }
          const wheel = wheels[0];
          if (request.url === "/wheel.json") {
            response.setHeader("Content-Type", "application/json");
            response.end(JSON.stringify({ url: `/wheels/${wheel}` }));
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
