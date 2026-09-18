import { fields } from "./schema.js";
export { fields, connection } from "./schema.js";
import type { Column, Job, Needs, Fulfilled } from "@malloy-runtime/compiler";
export const fileSearchPath = (root: string) =>
  `SET file_search_path = '${root.replaceAll("'", "''")}'`;
export interface Host {
  describe(sql: string): Promise<Column[]>;
  readURL(url: URL): Promise<string>;
}
export async function fulfil(needs: Needs, host: Host): Promise<Fulfilled> {
  const answer: Fulfilled = { urls: {}, schemas: {} };
  for (const url of needs.urls) {
    try {
      answer.urls[url] = { value: await host.readURL(new URL(url)) };
    } catch (error) {
      answer.urls[url] = { error: error instanceof Error ? error.message : String(error) };
    }
  }
  for (const schema of needs.schemas) {
    try {
      answer.schemas[schema.key] = { value: fields(await host.describe(schema.sql)) };
    } catch (error) {
      answer.schemas[schema.key] = {
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }
  return answer;
}
export async function drive<T>(job: Job<T>, host: Host): Promise<T> {
  try {
    let step = job.step();
    while ("needs" in step) step = job.step(await fulfil(step.needs, host));
    return step.result;
  } finally {
    job.close();
  }
}
export { stableResult } from "./result.js";
