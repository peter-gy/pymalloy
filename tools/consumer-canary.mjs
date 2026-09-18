import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..");
const directory = await mkdtemp(join(tmpdir(), "malloy-consumer-"));
try {
  const dependencies = {};
  for (const name of ["core", "duckdb", "node", "browser"]) {
    const cwd = join(root, "packages", name);
    const pkg = JSON.parse(await readFile(join(cwd, "package.json"), "utf8"));
    execFileSync("pnpm", ["pack", "--pack-destination", directory], { cwd, stdio: "pipe" });
    const filename = (await readdir(directory)).find((file) =>
      file.startsWith(pkg.name.replace("@", "").replace("/", "-")),
    );
    dependencies[pkg.name] = `file:${join(directory, filename)}`;
  }
  await writeFile(
    join(directory, "package.json"),
    JSON.stringify({
      private: true,
      type: "module",
      dependencies,
    }),
  );
  await writeFile(
    join(directory, "pnpm-workspace.yaml"),
    JSON.stringify({ overrides: dependencies }),
  );
  execFileSync("pnpm", ["install", "--ignore-scripts"], { cwd: directory, stdio: "inherit" });
  await writeFile(
    join(directory, "native.mjs"),
    `
    import {strict as assert} from 'node:assert';
    import {Session} from '@malloy-runtime/node';
    import {parseSource} from '@malloy-runtime/compiler/tooling';
    const session=await Session.open();
    try {
      const result=await session.run('run: duckdb.sql("SELECT 9007199254740993::BIGINT AS exact, 1.234567890123456789::DECIMAL(38,18) AS decimal_value") -> {select:*}');
      assert.equal(result.rows[0].exact,9007199254740993n);
      assert.equal(result.rows[0].decimal_value,'1.234567890123456789');
      assert.deepEqual(parseSource('run: missing').diagnostics,[]);
    } finally {await session.close();}
  `,
  );
  execFileSync("node", ["native.mjs"], { cwd: directory, stdio: "inherit" });
  await writeFile(
    join(directory, "browser.mjs"),
    "export {Session} from '@malloy-runtime/browser';",
  );
  await build({
    configFile: false,
    root: directory,
    build: {
      lib: {
        entry: join(directory, "browser.mjs"),
        formats: ["es"],
        fileName: () => "browser.mjs",
      },
      outDir: join(root, "nogit/consumer-canary"),
      emptyOutDir: true,
    },
  });
  console.log("Installed Node packages executed exact results. Browser consumer bundle built.");
} finally {
  await rm(directory, { recursive: true, force: true });
}
