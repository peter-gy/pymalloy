export { fields, connection } from "./schema";
import type { SchemaNeed } from "@malloy-runtime/compiler/jobs";
export const fileSearchPath = (root: string) =>
  `SET file_search_path = '${root.replaceAll("'", "''")}'`;
export function describeSQL(need: SchemaNeed): string {
  return `DESCRIBE ${need.kind === "table" ? need.tablePath : need.sql}`;
}

export { stableResult } from "./result";
