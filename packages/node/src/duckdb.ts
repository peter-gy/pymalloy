import { isAbsolute, resolve, win32 } from "node:path";
import { type DuckDBConnection, StatementType, type JS } from "@duckdb/node-api";

const readers = new Set([
  "read_csv",
  "read_csv_auto",
  "read_json",
  "read_json_auto",
  "read_ndjson",
  "read_ndjson_auto",
  "read_json_objects",
  "read_json_objects_auto",
  "read_ndjson_objects",
  "read_parquet",
  "parquet_scan",
  "read_text",
  "read_blob",
]);

type SQLValue = null | boolean | number | string | SQLValue[] | SQLNode;
interface SQLNode {
  [key: string]: SQLValue;
}

function isString(value: JS | undefined): value is string {
  return typeof value === "string";
}

function isNumber(value: SQLValue): value is number {
  return typeof value === "number";
}

function text(value: JS): string {
  if (!isString(value)) throw new TypeError("DuckDB returned a non-text SQL metadata value");
  return value;
}

function record(value: SQLValue | undefined): value is SQLNode {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function filePath(value: string): boolean {
  return /\.(csv|tsv|json|jsonl|ndjson|parquet)(?:\.|$)/i.test(value);
}

function rooted(value: string, root: string): string {
  return isAbsolute(value) || win32.isAbsolute(value) || /^[a-z][a-z\d+.-]*:/i.test(value)
    ? value
    : resolve(root, value);
}

function literal(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

function identifierKey(value: string): string {
  // DuckDB folds ASCII letters while non-ASCII identifier case remains significant.
  return value.replace(/[A-Z]/g, (character) => character.toLowerCase());
}

async function bindArgument(
  value: SQLValue | undefined,
  root: string,
  tableExists?: (name: string) => Promise<boolean>,
): Promise<void> {
  if (!record(value))
    throw new Error("File readers require a literal path or list of literal paths");
  if (value.function_name === "list_value" && Array.isArray(value.children)) {
    for (const child of value.children) await bindArgument(child, root, tableExists);
  } else if (value.class === "CONSTANT" && record(value.value) && isString(value.value.value)) {
    const path = value.value.value;
    if (!tableExists || (filePath(path) && !(await tableExists(path))))
      value.value.value = rooted(path, root);
  } else {
    throw new Error("File readers require a literal path or list of literal paths");
  }
}

async function bindTree(
  value: SQLValue | undefined,
  root: string,
  tableExists: (name: string) => Promise<boolean>,
  inherited = new Set<string>(),
): Promise<void> {
  if (Array.isArray(value)) {
    for (const item of value) await bindTree(item, root, tableExists, inherited);
    return;
  }
  if (!record(value)) return;
  const ctes = new Set(inherited);
  if (record(value.cte_map) && Array.isArray(value.cte_map.map)) {
    for (const cte of value.cte_map.map) {
      if (record(cte) && isString(cte.key)) {
        // A nonrecursive definition can read a same-named file or an outer CTE.
        await bindTree(cte.value, root, tableExists, ctes);
        ctes.add(identifierKey(cte.key));
      }
    }
  }
  if (value.type === "BASE_TABLE" && isString(value.table_name)) {
    const parts = [value.catalog_name, value.schema_name, value.table_name]
      .filter(Boolean)
      .map(String);
    const path = parts.join(".");
    const name = parts.map((part) => `"${part.replaceAll('"', '""')}"`).join(".");
    const isCTE = parts.length === 1 && ctes.has(identifierKey(path));
    if (filePath(path) && !isCTE && !(await tableExists(name))) {
      value.table_name = rooted(path, root);
      value.catalog_name = "";
      value.schema_name = "";
    }
  }
  if (value.type === "TABLE_FUNCTION" && record(value.function)) {
    const fn = value.function;
    if (isString(fn.function_name) && Array.isArray(fn.children) && fn.children.length) {
      const name = fn.function_name.toLowerCase();
      if (readers.has(name)) await bindArgument(fn.children[0], root);
      if (name === "query_table") {
        await bindArgument(fn.children[0], root, tableExists);
      }
    }
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === "cte_map") continue;
    let scope = ctes;
    if (value.type === "RECURSIVE_CTE_NODE" && key === "right" && isString(value.cte_name)) {
      scope = new Set(ctes).add(identifierKey(value.cte_name));
    }
    await bindTree(child, root, tableExists, scope);
  }
}

type Token = { text: string; start: number; end: number };

function tokens(sql: string): Token[] {
  const result: Token[] = [];
  for (let i = 0; i < sql.length;) {
    if (/\s/.test(sql[i])) {
      i++;
      continue;
    }
    if (sql.startsWith("--", i)) {
      const end = sql.indexOf("\n", i + 2);
      i = end === -1 ? sql.length : end + 1;
      continue;
    }
    if (sql.startsWith("/*", i)) {
      i += 2;
      let depth = 1;
      while (i < sql.length && depth) {
        if (sql.startsWith("/*", i)) {
          depth++;
          i += 2;
        } else if (sql.startsWith("*/", i)) {
          depth--;
          i += 2;
        } else i++;
      }
      if (depth) throw new Error("Unterminated SQL comment");
      continue;
    }
    const start = i;
    const char = sql[i++];
    if (char === "'" || char === '"') {
      const escaped =
        char === "'" &&
        /[eE]/.test(sql[start - 1] ?? "") &&
        (start < 2 || !/[A-Za-z_\d]/.test(sql[start - 2]));
      let closed = false;
      while (i < sql.length) {
        if (escaped && sql[i] === "\\") {
          i += 2;
          continue;
        }
        if (sql[i++] === char) {
          if (sql[i] === char) i++;
          else {
            closed = true;
            break;
          }
        }
      }
      if (!closed) throw new Error("Unterminated SQL literal");
    } else if (char === "$" && /^\$(?:[A-Za-z_][A-Za-z_\d]*)?\$/.test(sql.slice(start))) {
      const tag = sql.slice(start).match(/^\$(?:[A-Za-z_][A-Za-z_\d]*)?\$/)![0];
      const end = sql.indexOf(tag, start + tag.length);
      if (end < 0) throw new Error("Unterminated SQL dollar literal");
      i = end + tag.length;
    } else if (/[A-Za-z_]/.test(char)) {
      while (i < sql.length && /[A-Za-z_\d]/.test(sql[i])) i++;
    }
    result.push({ text: sql.slice(start, i), start, end: i });
  }
  return result;
}

export class DuckDBBackend {
  constructor(
    readonly connection: DuckDBConnection,
    private readonly assertActive: () => void,
  ) {}

  async bind(sql: string, root: string, allowWrite = false): Promise<string> {
    this.assertActive();
    const parsed = await this.connection.runAndReadAll(
      "SELECT json_serialize_sql(?::VARCHAR) AS ast",
      [sql],
    );
    // DuckDB serializes HUGEINT constants and unknown locations as JSON numbers.
    // Preserve their source spelling across edits to the surrounding AST.
    // SAFETY: Node 24 supplies rawJSON, which preserves numeric tokens during serialization.
    const json = JSON as typeof JSON & { rawJSON(value: string): { rawJSON: string } };
    // SAFETY: DuckDB returns its SQL AST as JSON. bindTree checks the node shapes it rewrites.
    const ast = JSON.parse(
      text(parsed.getRowObjectsJS()[0].ast),
      (_key: string, value: SQLValue, context?: { source: string }) =>
        isNumber(value) && !Number.isSafeInteger(value) && context
          ? json.rawJSON(context.source)
          : value,
    ) as SQLNode;
    if (ast.error) {
      if (allowWrite) return this.bindCopy(sql, root);
      throw new Error(
        `Data sources and queries require one SELECT statement: ${text(ast.error_message)}`,
      );
    }
    if (!Array.isArray(ast.statements) || ast.statements.length !== 1) {
      throw new Error("Data sources and queries require one SELECT statement");
    }
    const resolved = new Map<string, boolean>();
    await bindTree(ast, root, async (name) => {
      this.assertActive();
      if (resolved.has(name)) return resolved.get(name)!;
      let exists = true;
      try {
        await this.connection.runAndReadAll("SELECT 1 FROM pragma_table_info(?::VARCHAR) LIMIT 0", [
          name,
        ]);
      } catch (error) {
        if (
          !(error instanceof Error) ||
          !/^Catalog Error: (Table|Schema|Catalog) with name .* does not exist/s.test(error.message)
        ) {
          throw error;
        }
        exists = false;
      }
      resolved.set(name, exists);
      return exists;
    });
    this.assertActive();
    const result = await this.connection.runAndReadAll(
      "SELECT json_deserialize_sql(?::VARCHAR) AS sql",
      [JSON.stringify(ast)],
    );
    return text(result.getRowObjectsJS()[0].sql);
  }

  private async bindCopy(sql: string, root: string): Promise<string> {
    const parts = tokens(sql);
    if (parts[0]?.text.toUpperCase() !== "COPY" || parts[1]?.text !== "(") {
      throw new Error("SQL cells require one SELECT or COPY (SELECT ...) TO 'path' statement");
    }
    let depth = 1;
    let end = 2;
    for (; end < parts.length; end++) {
      if (parts[end].text === "(") depth++;
      if (parts[end].text === ")" && --depth === 0) break;
    }
    const destination = parts[end + 2];
    if (
      !destination ||
      parts[end + 1]?.text.toUpperCase() !== "TO" ||
      !destination.text.startsWith("'")
    ) {
      throw new Error("COPY requires a parenthesized SELECT and a literal destination path");
    }
    const query = await this.bind(sql.slice(parts[1].end, parts[end].start), root);
    const path = destination.text.slice(1, -1).replaceAll("''", "'");
    const output = `COPY (${query}) TO ${literal(rooted(path, root))}${sql.slice(destination.end)}`;
    if ((await this.connection.extractStatements(output)).count !== 1) {
      throw new Error("SQL cells require one SELECT or COPY statement");
    }
    return output;
  }

  async describe(sql: string, root: string): Promise<Array<{ name: string; type: string }>> {
    const bound = await this.bind(sql, root);
    this.assertActive();
    const result = await this.connection.runAndReadAll(`DESCRIBE ${bound}`);
    return result
      .getRowObjectsJS()
      .map((row) => ({ name: text(row.column_name), type: text(row.column_type) }));
  }

  async run(sql: string, root: string): Promise<Record<string, JS>[]> {
    const bound = await this.bind(sql, root, true);
    this.assertActive();
    const result = await this.connection.runAndReadAll(bound);
    return result.statementType === StatementType.COPY ? [] : result.getRowObjectsJS();
  }
}
