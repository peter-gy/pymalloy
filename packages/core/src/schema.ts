import {
  DuckDBDialect,
  type MalloyQueryData,
  mkFieldDef,
  sqlKey,
  type SQLSourceDef,
  type SQLSourceRequest,
  type TableSourceDef,
} from "@malloydata/malloy";
import { BaseConnection } from "@malloydata/malloy/connection";

export interface Column {
  name: string;
  type: string;
}

export class SchemaConnection extends BaseConnection {
  readonly name = "duckdb";
  readonly dialectName = "duckdb";
  private readonly dialect = new DuckDBDialect();

  constructor(private readonly describe: (sql: string) => Promise<Column[]>) {
    super();
  }

  getDigest() {
    return "pymalloy-duckdb";
  }

  runSQL(): Promise<MalloyQueryData> {
    throw new Error("Schema connections describe queries. Execute through a session.");
  }

  private async fields(sql: string) {
    return (await this.describe(sql)).map(({ name, type }) =>
      mkFieldDef(this.dialect.parseDuckDBType(type), name),
    );
  }

  async fetchTableSchema(name: string, tablePath: string): Promise<TableSourceDef> {
    return {
      type: "table",
      name,
      tablePath,
      connection: this.name,
      dialect: this.dialectName,
      fields: await this.fields(`SELECT * FROM ${tablePath}`),
    };
  }

  async fetchSelectSchema(request: SQLSourceRequest): Promise<SQLSourceDef> {
    return {
      ...request,
      type: "sql_select",
      name: sqlKey(request.connection, request.selectStr),
      dialect: this.dialectName,
      fields: await this.fields(request.selectStr),
    };
  }
}
