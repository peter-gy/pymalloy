import { defineConfig, devices } from "@playwright/test";

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
      name: "jupyterlab",
      testMatch: "jupyter.spec.ts",
      use: { baseURL: "http://127.0.0.1:28442" },
    },
    { name: "pyodide", testMatch: "pyodide.spec.ts", use: { baseURL: "http://127.0.0.1:28443" } },
    {
      name: "browser",
      testMatch: /browser(?:-failure)?\.spec\.ts/,
      use: { baseURL: "http://127.0.0.1:28443" },
    },
  ],
  webServer: [
    {
      command:
        "uv run --no-sync marimo run apps/e2e/fixtures/notebook.py --headless --host 127.0.0.1 --port 28441 --no-token --session-ttl 0",
      cwd: "../..",
      url: "http://127.0.0.1:28441",
      reuseExistingServer: false,
      timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      command: "uv run --no-sync python apps/e2e/serve_jupyter.py",
      cwd: "../..",
      url: "http://127.0.0.1:28442/lab",
      reuseExistingServer: false,
      timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
    },
    {
      command: "pnpm --filter @pymalloy/e2e browser:dev",
      cwd: "../..",
      url: "http://127.0.0.1:28443",
      reuseExistingServer: false,
      timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
  ],
});
