import { DuckDBDialect, mkFieldDef } from "@malloydata/malloy";
import type { Column } from "@malloy-runtime/compiler";
const dialect = new DuckDBDialect();
export const connection = { name: "duckdb", dialect: "duckdb" };
export const fields = (columns: Column[]) =>
  columns.map(({ name, type }) => mkFieldDef(dialect.parseDuckDBType(type), name));
