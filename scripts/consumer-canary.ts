import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { build } from "vite";

const root = resolve(import.meta.dirname, "..");
const require = createRequire(import.meta.url);
const directory = await mkdtemp(join(tmpdir(), "malloy-consumer-"));
try {
  const dependencies: Record<string, string> = {};
  for (const name of ["core", "duckdb", "node", "browser"]) {
    const cwd = join(root, "packages", name);
    const pkg = JSON.parse(await readFile(join(cwd, "package.json"), "utf8"));
    execFileSync("pnpm", ["pack", "--pack-destination", directory], { cwd, stdio: "pipe" });
    const filename = (await readdir(directory)).find((file) =>
      file.startsWith(pkg.name.replace("@", "").replace("/", "-")),
    );
    if (!filename) throw new Error(`Missing package archive for ${pkg.name}`);
    dependencies[pkg.name] = `file:${join(directory, filename)}`;
  }
  await writeFile(
    join(directory, "package.json"),
    JSON.stringify({
      packageManager: JSON.parse(await readFile(join(root, "package.json"), "utf8")).packageManager,
      private: true,
      type: "module",
      dependencies,
      devDependencies: Object.fromEntries(
        await Promise.all(
          ["typescript", "@types/node"].map(async (name) => [
            name,
            JSON.parse(await readFile(require.resolve(`${name}/package.json`), "utf8")).version,
          ]),
        ),
      ),
    }),
  );
  await writeFile(
    join(directory, "pnpm-workspace.yaml"),
    JSON.stringify({ overrides: dependencies }),
  );
  execFileSync("pnpm", ["install", "--ignore-scripts"], { cwd: directory, stdio: "inherit" });
  await writeFile(
    join(directory, "consumer.ts"),
    `
    import {Session, Model, Query, ToolingError, type Result, type ModelSource, type QueryOptions} from '@malloy-runtime/node';
    import {Session as BrowserSession, type Files} from '@malloy-runtime/browser';
    import {parseSource, formatSource} from '@malloy-runtime/compiler/tooling';
    import {type Inspection, type DocumentOptions} from '@malloy-runtime/compiler';
    export async function native(source: ModelSource, options: QueryOptions): Promise<Result> {
      const session = await Session.open();
      try {
        const model: Model = await session.model({source});
        const query: Query = model.query();
        const inspection: Inspection = model.inspect();
        const document: DocumentOptions = {all: true};
        await model.document(document);
        parseSource(formatSource(model.source().text).source);
        return await query.run(options);
      } catch (error) {
        if (error instanceof ToolingError) console.error(error.diagnostics);
        throw error;
      } finally {await session.close();}
    }
    export async function browser(files: Files) {
      const session = await BrowserSession.open();
      try {return await session.run('run: duckdb.sql("SELECT 42 AS answer") -> {select:*}', {files});}
      finally {await session.close();}
    }
  `,
  );
  for (const [module, moduleResolution] of [
    ["NodeNext", "NodeNext"],
    ["ESNext", "Bundler"],
  ]) {
    await writeFile(
      join(directory, "tsconfig.json"),
      JSON.stringify({
        compilerOptions: {
          target: "ES2023",
          module,
          moduleResolution,
          strict: true,
          noEmit: true,
          types: ["node"],
        },
        files: ["consumer.ts"],
      }),
    );
    execFileSync("pnpm", ["exec", "tsc"], { cwd: directory, stdio: "inherit" });
  }
  await writeFile(
    join(directory, "native.mjs"),
    `
    import {strict as assert} from 'node:assert';
    import {Session} from '@malloy-runtime/node';
    import {Worker} from 'node:worker_threads';
    import * as compiler from '@malloy-runtime/compiler';
    globalThis.Worker = Worker;
    const browser = await import('@malloy-runtime/browser');
    for (const name of ['Model', 'Query', 'ToolingError']) assert.equal(browser[name], compiler[name]);
    assert.ok(new browser.ToolingError('fixture') instanceof compiler.ToolingError);
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
    `
    import * as browser from '@malloy-runtime/browser';
    import * as compiler from '@malloy-runtime/compiler';
    for (const name of ['Model', 'Query', 'ToolingError']) {
      if (browser[name] !== compiler[name]) throw new Error(name + ' class identity differs');
    }
    export {Session, Model, Query, ToolingError} from '@malloy-runtime/browser';
    `,
  );
  await build({
    configFile: false,
    define: { "process.env": "{}", global: "globalThis" },
    root: directory,
    build: {
      lib: {
        entry: join(directory, "browser.mjs"),
        formats: ["es"],
        fileName: () => "browser.mjs",
      },
      outDir: join(directory, "dist"),
      emptyOutDir: true,
    },
  });
  execFileSync(
    "pnpm",
    [
      "--filter",
      "@pymalloy/e2e",
      "exec",
      "playwright",
      "test",
      "--project=browser",
      "--reporter=list",
      "--output",
      join(directory, "test-results"),
      "--grep",
      "retained models own competing file mappings and preserve exact result values",
    ],
    {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, PYMALLOY_BROWSER_BUNDLE: join(directory, "dist", "browser.mjs") },
    },
  );
  console.log(
    "Installed declarations passed NodeNext and Bundler typechecks. Node executed exact results. Packed browser executed exact results and shared compiler classes.",
  );
} finally {
  await rm(directory, { recursive: true, force: true });
}
