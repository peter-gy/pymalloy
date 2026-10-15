import type { FieldDef } from "@malloydata/malloy";
import type { Job, Needs, Fulfilled, SchemaNeed } from "./job";

export interface Host {
  readonly signal?: AbortSignal;
  schema(need: SchemaNeed): Promise<FieldDef[]>;
  readURL(url: URL): Promise<string>;
}
async function fulfil(needs: Needs, host: Host): Promise<Fulfilled> {
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
      answer.schemas[schema.key] = { value: await host.schema(schema) };
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
