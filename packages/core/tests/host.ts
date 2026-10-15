import { checkSource } from "../src/tooling";
import { drive as fulfilJob } from "../src/drive";
import { connection, fields, describeSQL } from "../../duckdb/src/index";
import { CompiledModel, type Job, type LoadOptions } from "../src/jobs";
import { documentKind, type SourcePosition } from "../src/index";
interface Fixture extends Omit<LoadOptions, "connection"> {
  describe(sql: string): Promise<{ name: string; type: string }[]>;
  readURL(url: URL): Promise<string>;
  position?: SourcePosition;
  syntaxOnly?: boolean;
}
const defaults = {
  describe: async () => [{ name: "value", type: "INTEGER" }],
  readURL: async (url: URL) => {
    throw new Error(`Missing source: ${url}`);
  },
};
export function drive<T>(job: Job<T>, host = defaults): Promise<T> {
  return fulfilJob(job, {
    readURL: host.readURL,
    schema: async (need) => fields(await host.describe(describeSQL(need))),
  });
}
export function compile(options: Fixture) {
  return drive(
    CompiledModel.begin({
      ...options,
      connection,
      documentKind: options.documentKind ?? documentKind(options.url),
    }),
    options,
  );
}
export function check(options: Fixture) {
  return drive(
    checkSource({
      ...options,
      connection,
      documentKind: options.documentKind ?? documentKind(options.url),
    }),
    options,
  );
}
