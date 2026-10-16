export { fields, connection } from "./schema";
import type { SchemaNeed } from "@malloy-runtime/compiler/jobs";
export const fileSearchPath = (root: string) =>
  `SET file_search_path = '${root.replaceAll("'", "''")}'`;
export function describeSQL(need: SchemaNeed): string {
  return `DESCRIBE ${need.kind === "table" ? need.tablePath : need.sql}`;
}

export function previewSQL(sql: string, limit: number): string {
  // DuckDB's query table function validates one SELECT before executing it.
  return `SELECT * FROM query('${sql.replaceAll("'", "''")}') LIMIT ${limit}`;
}

export { stableResult } from "./result";
