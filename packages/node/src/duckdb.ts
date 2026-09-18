import { stableResult } from "@malloy-runtime/duckdb";
import {
  type DuckDBConnection,
  StatementType,
  type JS,
  JSDuckDBValueConverter,
  DuckDBTypeId,
  type DuckDBValueConverter,
} from "@duckdb/node-api";
import type { Result, Row } from "@malloy-runtime/compiler";
function isText(value: JS): value is string {
  return typeof value === "string";
}
function text(value: JS): string {
  if (!isText(value)) throw new TypeError("DuckDB metadata must be text");
  return value;
}
const convert: DuckDBValueConverter<JS> = (value, type, converter) => {
  if (type.typeId === DuckDBTypeId.DECIMAL && value !== null) return value.toString();
  return JSDuckDBValueConverter(value, type, converter);
};
export class DuckDBBackend {
  constructor(readonly connection: DuckDBConnection) {}
  async describe(sql: string) {
    const result = await this.connection.runAndReadAll(`DESCRIBE ${sql}`);
    return result
      .getRowObjectsJS()
      .map((row) => ({ name: text(row.column_name), type: text(row.column_type) }));
  }
  async run(sql: string, template?: Result["malloy"]): Promise<Result> {
    const statements = await this.connection.extractStatements(sql);
    if (statements.count !== 1)
      throw new Error("Query execution requires one SELECT or COPY statement");
    const prepared = await statements.prepare(0);
    try {
      if (
        prepared.statementType !== StatementType.SELECT &&
        prepared.statementType !== StatementType.COPY
      )
        throw new Error("Query execution requires one SELECT or COPY statement");
      const result = await prepared.runAndReadAll();
      const columns = result
        .columnNames()
        .map((name, index) => ({ name, type: result.columnType(index).toString() }));
      // SAFETY: DuckDB's JS converter materializes primitives, typed arrays, lists, and records.
      const rows =
        result.statementType === StatementType.COPY
          ? []
          : (result.convertRowObjects(convert) as Row[]);
      return { sql, columns, rows, malloy: stableResult(sql, columns, rows, template) };
    } finally {
      prepared.destroySync();
    }
  }
}
