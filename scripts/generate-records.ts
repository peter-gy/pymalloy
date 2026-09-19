import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createGenerator } from "ts-json-schema-generator";
import { generateLexicon } from "./lexicon.ts";

const root = resolve(import.meta.dirname, "..");
const args = process.argv.slice(2);
if (args.length > 1 || (args.length === 1 && args[0] !== "--check")) {
  throw new Error("Usage: pnpm records [--check]");
}
const check = args[0] === "--check";
const directory = await mkdtemp(join(root, ".pymalloy-records-"));
const outputs = [
  ["protocol.json", "packages/protocol/schema/protocol.json"],
  ["records.py", "packages/python/src/pymalloy/_protocol/records.py"],
  ["lexicon.py", "packages/python/src/pymalloy/_authoring/lexicon.py"],
] as const;
try {
  const schema = createGenerator({
    path: join(root, "packages/protocol/src/records.ts"),
    type: "Records",
    tsconfig: join(root, "packages/protocol/schema/tsconfig.json"),
    skipTypeCheck: true,
  }).createSchema("Records");
  await writeFile(join(directory, "protocol.json"), JSON.stringify(schema, null, 2) + "\n");
  await writeFile(join(directory, "lexicon.py"), generateLexicon());
  await writeFile(
    join(directory, "python-model-options.json"),
    JSON.stringify({
      "#all#": { base_class_kwargs: { frozen: true, forbid_unknown_fields: true } },
    }),
  );
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "python",
      "-m",
      "datamodel_code_generator",
      "--input",
      join(directory, "protocol.json"),
      "--output",
      join(directory, "records.py"),
      "--input-file-type",
      "jsonschema",
      "--output-model-type",
      "msgspec.Struct",
      "--snake-case-field",
      "--enum-field-as-literal",
      "all",
      "--disable-timestamp",
      "--use-schema-description",
      "--use-standard-collections",
      "--target-python-version",
      "3.12",
      "--use-generic-container-types",
      "--formatters",
      "ruff-check",
      "ruff-format",
      "--keyword-only",
      "--extra-template-data",
      join(directory, "python-model-options.json"),
    ],
    { cwd: root, stdio: "inherit" },
  );
  execFileSync("pnpm", ["exec", "vp", "fmt", join(directory, "protocol.json")], {
    cwd: root,
    stdio: "inherit",
  });
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "ruff",
      "format",
      "--config",
      join(root, "pyproject.toml"),
      join(directory, "records.py"),
      join(directory, "lexicon.py"),
    ],
    { cwd: root, stdio: "inherit" },
  );
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "python",
      "-c",
      `
import importlib.util
import sys
import msgspec
spec = importlib.util.spec_from_file_location("generated_protocol", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
msgspec.json.Decoder(module.Records)
`,
      join(directory, "records.py"),
    ],
    { cwd: root, stdio: "inherit" },
  );
  const changed: string[] = [];
  for (const [name, destination] of outputs) {
    const generated = await readFile(join(directory, name));
    const target = join(root, destination);
    if (!existsSync(target) || !generated.equals(await readFile(target))) changed.push(destination);
  }
  if (check) {
    if (changed.length)
      throw new Error(`Generated files are stale. Run pnpm records:\n${changed.join("\n")}`);
    console.log("Protocol schema, Python records and Malloy lexicon are current.");
  } else {
    for (const [name, destination] of outputs) {
      if (changed.includes(destination))
        await rename(join(directory, name), join(root, destination));
    }
    console.log(`Updated ${changed.length} generated files.`);
  }
} finally {
  await rm(directory, { recursive: true, force: true });
}
