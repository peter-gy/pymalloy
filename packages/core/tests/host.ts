import { checkSource } from "../src/tooling.js";
import { DuckDBDialect, mkFieldDef } from "@malloydata/malloy";
import {
  CompiledModel,
  type Job,
  type Fulfilled,
  type LoadOptions,
  type SourcePosition,
} from "../src/index.js";
interface Fixture extends Omit<LoadOptions, "connection"> {
  describe(sql: string): Promise<{ name: string; type: string }[]>;
  readURL(url: URL): Promise<string>;
  position?: SourcePosition;
  syntaxOnly?: boolean;
}
const dialect = new DuckDBDialect();
const defaults = {
  describe: async () => [{ name: "value", type: "INTEGER" }],
  readURL: async (url: URL) => {
    throw new Error(`Missing source: ${url}`);
  },
};
export async function drive<T>(job: Job<T>, host = defaults): Promise<T> {
  let step = job.step();
  while ("needs" in step) {
    const fulfilled: Fulfilled = { urls: {}, schemas: {} };
    for (const url of step.needs.urls) {
      try {
        fulfilled.urls[url] = { value: await host.readURL(new URL(url)) };
      } catch (error) {
        fulfilled.urls[url] = { error: String(error) };
      }
    }
    for (const need of step.needs.schemas) {
      try {
        fulfilled.schemas[need.key] = {
          value: (await host.describe(need.sql)).map((c) =>
            mkFieldDef(dialect.parseDuckDBType(c.type), c.name),
          ),
        };
      } catch (error) {
        fulfilled.schemas[need.key] = { error: String(error) };
      }
    }
    step = job.step(fulfilled);
  }
  return step.result;
}
export function compile(options: Fixture) {
  return drive(
    CompiledModel.begin({ ...options, connection: { name: "duckdb", dialect: "duckdb" } }),
    options,
  );
}
export function check(options: Fixture) {
  return drive(
    checkSource({ ...options, connection: { name: "duckdb", dialect: "duckdb" } }),
    options,
  );
}
