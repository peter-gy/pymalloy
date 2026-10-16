import { defineConfig, devices } from "@playwright/test";

const selectedProjects = process.argv.flatMap((argument, index, arguments_) =>
  argument === "--project"
    ? [arguments_[index + 1]]
    : argument.startsWith("--project=")
      ? [argument.slice("--project=".length)]
      : [],
);
const selected = (project: string) =>
  selectedProjects.length
    ? selectedProjects.includes(project)
    : !process.env.PYMALLOY_BROWSER_BUNDLE;

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  use: {
    ...devices["Desktop Chrome"],
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "marimo", testMatch: "marimo.spec.ts", use: { baseURL: "http://127.0.0.1:28441" } },
    {
      name: "marimo-export",
      testMatch: "marimo-export.spec.ts",
      use: { baseURL: "http://127.0.0.1:28444" },
    },
    {
      name: "jupyterlab",
      testMatch: "jupyter.spec.ts",
      use: { baseURL: "http://127.0.0.1:28442" },
    },
    {
      name: "pyodide",
      testMatch: /pyodide(?:-api)?\.spec\.ts/,
      use: { baseURL: "http://127.0.0.1:28443" },
    },
    {
      name: "jupyterlite",
      testMatch: "jupyterlite.spec.ts",
      use: { baseURL: "http://127.0.0.1:28445" },
    },
    {
      name: "marimo-wasm",
      testMatch: "marimo-wasm.spec.ts",
      use: { baseURL: "http://127.0.0.1:28446" },
    },
    {
      name: "browser",
      testMatch: /browser(?:-failure)?\.spec\.ts/,
      use: { baseURL: "http://127.0.0.1:28443" },
    },
  ],
  webServer: [
    ...(selected("marimo-wasm")
      ? [
          {
            command:
              "uv run --isolated --frozen --only-group notebook-hosts python apps/e2e/serve_marimo_wasm.py",
            cwd: "../..",
            url: "http://127.0.0.1:28446",
            reuseExistingServer: false,
            timeout: 120_000,
            gracefulShutdown: { signal: "SIGTERM" as const, timeout: 5_000 },
          },
        ]
      : []),
    ...(selected("jupyterlite")
      ? [
          {
            command:
              "uv run --isolated --frozen --only-group notebook-hosts python apps/e2e/serve_jupyterlite.py",
            cwd: "../..",
            url: "http://127.0.0.1:28445/lab/index.html",
            reuseExistingServer: false,
            timeout: 120_000,
            gracefulShutdown: { signal: "SIGTERM" as const, timeout: 5_000 },
          },
        ]
      : []),
    ...(selected("marimo")
      ? [
          {
            command:
              "uv run --no-sync marimo run apps/e2e/fixtures/notebook.py --headless --host 127.0.0.1 --port 28441 --no-token --session-ttl 0",
            cwd: "../..",
            url: "http://127.0.0.1:28441",
            reuseExistingServer: false,
            timeout: 60_000,
            gracefulShutdown: { signal: "SIGTERM" as const, timeout: 5_000 },
          },
        ]
      : []),
    ...(selected("jupyterlab")
      ? [
          {
            command: "uv run --no-sync python apps/e2e/serve_jupyter.py",
            cwd: "../..",
            url: "http://127.0.0.1:28442/lab",
            reuseExistingServer: false,
            timeout: 120_000,
            gracefulShutdown: { signal: "SIGTERM" as const, timeout: 10_000 },
          },
        ]
      : []),
    ...(selected("marimo-export")
      ? [
          {
            command: "uv run --no-sync python apps/e2e/serve_marimo_export.py",
            cwd: "../..",
            url: "http://127.0.0.1:28444",
            reuseExistingServer: false,
            timeout: 120_000,
            gracefulShutdown: { signal: "SIGTERM" as const, timeout: 5_000 },
          },
        ]
      : []),
    {
      command: "pnpm --filter @pymalloy/e2e browser:dev",
      cwd: "../..",
      url: "http://127.0.0.1:28443",
      reuseExistingServer: false,
      timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM" as const, timeout: 5_000 },
    },
  ],
});
