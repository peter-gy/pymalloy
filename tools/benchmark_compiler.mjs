/** Measure compiler-owned work independently of database and process startup. */
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { connection, drive } from "../packages/duckdb/dist/index.mjs";

const { values } = parseArgs({
  options: {
    output: { type: "string" },
    samples: { type: "string", default: "7" },
    compiler: { type: "string", default: "packages/core/dist" },
  },
});
if (!values.output) throw new Error("Pass --output timings.json");
const samples = Number(values.samples);
if (!Number.isSafeInteger(samples) || samples < 1) throw new Error("samples must be positive");
const { CompiledModel } = await import(pathToFileURL(resolve(values.compiler, "index.mjs")).href);
const { checkSource, compilerVersion } = await import(
  pathToFileURL(resolve(values.compiler, "tooling.mjs")).href
);
const timings = {};
const preparationsPerSample = 100;
const url = new URL("memory://benchmark/model.malloy");
const host = {
  describe: async () => [{ name: "value", type: "INTEGER" }],
  readURL: async () => {
    throw new Error("Fixture imports must be closed");
  },
};
const execute = (job) => drive(job, host);
async function measure(name, operation) {
  const begin = performance.now();
  const result = await operation();
  (timings[name] ??= []).push((performance.now() - begin) / 1000);
  return result;
}
for (const count of [100, 1000]) {
  const source =
    "##! experimental.givens\n" +
    Array.from({ length: count }, (_, i) => `given: p_${i} :: number is ${i}`).join("\n") +
    "\nsource: s is duckdb.sql('SELECT 1 AS value')\nrun: s -> {select: value}";
  const model = await execute(CompiledModel.begin({ source, url, connection }));
  model.inspect();
  for (let i = 0; i < samples; i++) await measure(`inspect_${count}_givens`, () => model.inspect());
  const sources = Array.from(
    { length: count },
    (_, i) => `source: s_${i} is duckdb.table('t_${i}') extend {measure: total is value.sum()}`,
  ).join("\n");
  await execute(checkSource({ source: sources, url, connection }));
  for (let i = 0; i < samples; i++)
    await measure(`check_${count}_sources`, () =>
      execute(checkSource({ source: sources, url, connection })),
    );
}
const aggregates = Array.from({ length: 100 }, (_, i) => `v_${i} is sum(value + ${i})`).join("\n");
const parameterized = await execute(
  CompiledModel.begin({
    url,
    connection,
    source: `##! experimental.givens\ngiven: minimum :: number is 0\nsource: s is duckdb.sql('SELECT 1 AS value')\nquery: totals is s -> {where: value > $minimum aggregate: ${aggregates}}`,
  }),
);
await execute(parameterized.prepare("totals"));
for (let i = 0; i < samples; i++) {
  await measure("prepare_default_100_aggregates", async () => {
    for (let j = 0; j < preparationsPerSample; j++) await execute(parameterized.prepare("totals"));
  });
  await measure("prepare_bound_100_aggregates", async () => {
    for (let j = 0; j < preparationsPerSample; j++)
      await execute(parameterized.prepare("totals", { givens: { minimum: j } }));
  });
}
const seconds = Object.fromEntries(
  Object.entries(timings).map(([name, measurements]) => {
    const ordered = measurements.toSorted((a, b) => a - b);
    return [
      name,
      {
        median:
          (ordered[Math.floor((ordered.length - 1) / 2)] +
            ordered[Math.floor(ordered.length / 2)]) /
          2,
        samples: measurements,
      },
    ];
  }),
);
await mkdir(dirname(resolve(values.output)), { recursive: true });
await writeFile(
  values.output,
  JSON.stringify(
    {
      compiler: compilerVersion,
      node: process.version,
      samples,
      preparationsPerSample,
      notes:
        "Warm in-process compiler with the shared host driver and one integer field per schema. Inspection repeats on one retained model; each check has a fresh compilation.",
      seconds,
    },
    null,
    2,
  ) + "\n",
);
console.log(
  JSON.stringify(
    Object.fromEntries(Object.entries(seconds).map(([name, value]) => [name, value.median])),
    null,
    2,
  ),
);
