import { fields } from "./schema";
export { fields, connection } from "./schema";
import type { Column, Job, Needs, Fulfilled, SchemaNeed } from "@malloy-runtime/compiler";
export const fileSearchPath = (root: string) =>
  `SET file_search_path = '${root.replaceAll("'", "''")}'`;
export function describeSQL(need: SchemaNeed): string {
  return `DESCRIBE ${need.kind === "table" ? need.tablePath : need.sql}`;
}

export interface Host {
  readonly signal?: AbortSignal;
  describe(sql: string): Promise<Column[]>;
  readURL(url: URL): Promise<string>;
}
export async function fulfil(needs: Needs, host: Host): Promise<Fulfilled> {
  const answer: Fulfilled = { urls: {}, schemas: {} };
  for (const url of needs.urls) {
    host.signal?.throwIfAborted();
    try {
      answer.urls[url] = { value: await host.readURL(new URL(url)) };
    } catch (error) {
      host.signal?.throwIfAborted();
      answer.urls[url] = { error: error instanceof Error ? error.message : String(error) };
    }
  }
  for (const schema of needs.schemas) {
    host.signal?.throwIfAborted();
    try {
      answer.schemas[schema.key] = { value: fields(await host.describe(describeSQL(schema))) };
    } catch (error) {
      host.signal?.throwIfAborted();
      answer.schemas[schema.key] = {
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }
  return answer;
}
export async function drive<T>(job: Job<T>, host: Host): Promise<T> {
  try {
    host.signal?.throwIfAborted();
    let step = job.step();
    while ("needs" in step) {
      const answers = await fulfil(step.needs, host);
      host.signal?.throwIfAborted();
      step = job.step(answers);
    }
    return step.result;
  } finally {
    job.close();
  }
}
export { stableResult } from "./result";
