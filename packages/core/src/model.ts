import { type GivenValue, type PreparedQuery } from "@malloydata/malloy";
import { loadSource, type LoadOptions } from "./compile.js";
import { ToolingError, toolingError } from "./diagnostics.js";
import { inspectModel, referenceAt, type Inspection, type ReferenceInfo } from "./inspect.js";
import type { NativeMetadata } from "./upstream.js";
import { compilerVersion, parseSource, type ParseReport, type Position } from "./tools.js";

export type Cell =
  | { kind: "markdown"; text: string }
  | {
      kind: "query";
      name: string;
      sql: string;
    };

export interface SourceBundle {
  url: string;
  text: string;
  imports: Record<string, string>;
}

export class CompiledModel {
  private readonly runs: string[];
  private readonly named: string[];
  private readonly views = new Map<string, { source: string; view: string }>();
  private readonly sqlStatements;
  private readonly sqlNames: string[];
  readonly queries: readonly string[];

  private constructor(private readonly details: Awaited<ReturnType<typeof loadSource>>) {
    const { model, statements } = details;
    const { named, unnamed } = model.queries();
    this.named = named;
    this.runs = Array.from({ length: unnamed }, (_, i) => `run:${i + 1}`);
    const selectors = new Set<string>();
    const addSelector = (selector: string) => {
      if (selectors.has(selector)) {
        throw new Error(
          `Ambiguous query selector '${selector}'. Rename the conflicting query, source, or view.`,
        );
      }
      selectors.add(selector);
    };
    for (const selector of [...this.runs, ...named]) addSelector(selector);
    for (const source of model.exportedExplores) {
      for (const field of source.structDef.fields) {
        if (field.type === "turtle" && field.accessModifier === undefined) {
          const view = field.as ?? field.name;
          const selector = `${source.name}.${view}`;
          addSelector(selector);
          this.views.set(selector, {
            source: source.name,
            view,
          });
        }
      }
    }
    this.sqlStatements = statements?.filter((statement) => statement.type === "sql") ?? [];
    this.sqlNames = this.sqlStatements.map((_, i) => `sql:${i + 1}`);
    for (const selector of this.sqlNames) addSelector(selector);
    this.queries = Object.freeze([...selectors]);
  }

  static async load(options: LoadOptions): Promise<CompiledModel> {
    return new CompiledModel(await loadSource(options));
  }

  source(): SourceBundle {
    return {
      url: this.details.url.href,
      text: this.details.document,
      imports: Object.fromEntries(this.details.imports),
    };
  }

  inspect(): Inspection {
    return inspectModel(this.details.model, this.queries, this.details.locations, this.details.url);
  }

  reference(position: Position & { url?: URL }): ReferenceInfo {
    return referenceAt(
      this.details.model,
      this.details.parse,
      position,
      this.details.locations,
      this.details.url,
    );
  }

  async query(
    selector?: string | null,
    source?: string | null,
    givens?: Record<string, GivenValue>,
  ): Promise<{ name: string; sql: string; line?: number }> {
    try {
      return await this.prepareQuery(selector, source, structuredClone(givens));
    } catch (error) {
      toolingError(error, this.details.locations);
    }
  }

  private async prepareQuery(
    selector?: string | null,
    source?: string | null,
    givens?: Record<string, GivenValue>,
  ) {
    const { model, compile } = this.details;
    if (source !== undefined && source !== null) {
      const extended = await compile({ model, source });
      return {
        name: "query",
        sql: extended.preparedQuery.getPreparedResult({ givens }).sql,
      };
    }
    const name =
      selector ?? this.runs.at(-1) ?? (this.queries.length === 1 ? this.queries[0] : undefined);
    if (name === undefined) {
      throw new Error(
        `Choose a query from: ${this.queries.join(", ") || "the model has no queries"}`,
      );
    }
    if (this.sqlNames.includes(name)) {
      const statement = this.sqlStatements[this.sqlNames.indexOf(name)];
      if (statement.config?.connection !== "duckdb") {
        throw new Error(`SQL cell '${name}' requires the duckdb connection`);
      }
      const characters = Array.from(statement.text);
      const lineOffsets = [0];
      for (const [index, character] of characters.entries()) {
        if (character === "\n") lineOffsets.push(index + 1);
      }
      const offset = (position: Position) => {
        const line = position.line - statement.range.start.line;
        return (
          lineOffsets[line] +
          position.character -
          (line === 0 ? statement.range.start.character : 0)
        );
      };
      const replacements = [];
      for (const embedded of statement.embeddedMalloyQueries) {
        const extended = await compile({
          model,
          source: `run: ${embedded.query}`,
          location: { url: this.details.url.href, range: embedded.malloyRange },
        });
        replacements.push({
          start: offset(embedded.range.start),
          end: offset(embedded.range.end),
          sql: `(${extended.preparedQuery.getPreparedResult({ givens }).sql})`,
        });
      }
      for (const replacement of replacements.reverse()) {
        characters.splice(replacement.start, replacement.end - replacement.start, replacement.sql);
      }
      return { name, sql: characters.join(""), line: statement.range.start.line };
    }
    let query: PreparedQuery;
    if (this.runs.includes(name)) {
      query = model.getPreparedQueryByIndex(this.runs.indexOf(name));
    } else if (this.named.includes(name)) {
      query = model.getPreparedQueryByName(name);
    } else if (this.views.has(name)) {
      const { source, view } = this.views.get(name)!;
      const quote = (value: string) => "`" + value.replaceAll("`", "\\`") + "`";
      const extended = await compile({
        model,
        source: `run: ${quote(source)} -> ${quote(view)}`,
      });
      query = extended.preparedQuery;
    } else {
      throw new Error(`Unknown query '${name}'. Choose from: ${this.queries.join(", ")}`);
    }
    const result = query.getPreparedResult({ givens });
    if (result.connectionName !== "duckdb") {
      throw new Error(`Query '${name}' requires the duckdb connection`);
    }
    return { name, sql: result.sql, line: query.location?.range.start.line };
  }

  async document(selectors: string[], givens?: Record<string, GivenValue>): Promise<Cell[]> {
    const { model, statements } = this.details;
    selectors = [...selectors];
    givens = structuredClone(givens);
    const selected = selectors.includes("*")
      ? this.queries
      : selectors.length
        ? selectors
        : statements
          ? [...this.runs, ...this.sqlNames]
          : this.runs.length
            ? this.runs
            : this.named.length
              ? this.named
              : [...this.views.keys()];
    const compiled = [];
    for (const selector of selected) compiled.push(await this.query(selector, undefined, givens));
    const cells: Cell[] = [];
    if (statements && !selectors.length) {
      for (const statement of statements) {
        if (statement.type === "markdown") {
          cells.push({ kind: "markdown", text: statement.text });
        } else {
          for (const query of compiled) {
            if (
              query.line !== undefined &&
              query.line >= statement.range.start.line &&
              query.line <= statement.range.end.line
            )
              cells.push({ kind: "query", name: query.name, sql: query.sql });
          }
        }
      }
    } else {
      for (const query of compiled) {
        cells.push({ kind: "query", name: query.name, sql: query.sql });
      }
    }
    if (!cells.length) {
      cells.push({
        kind: "markdown",
        text:
          "## Sources\n\n" +
          model.exportedExplores.map((source) => `- \`${source.name}\``).join("\n"),
      });
    }
    return cells;
  }
}

export interface CheckOptions extends LoadOptions {
  position?: Position;
  syntaxOnly?: boolean;
}

export interface CheckReport extends ParseReport {
  ok: boolean;
  compiler_version: string;
  native: NativeMetadata;
  queries: string[];
}

export async function checkSource(options: CheckOptions): Promise<CheckReport> {
  const source = options.source ?? (await options.readURL(options.url));
  const parsed = parseSource(source, options);
  const report = {
    ...parsed,
    ok: !parsed.diagnostics.some((problem) => problem.severity === "error"),
    compiler_version: compilerVersion,
    native: { model: null, sources: [] },
    queries: [],
  };
  if (options.syntaxOnly || !report.ok) return report;
  try {
    const compiled = await CompiledModel.load({ ...options, source });
    const inspection = compiled.inspect();
    return {
      ...report,
      ok: true,
      diagnostics: inspection.diagnostics,
      native: inspection.native,
      queries: [...compiled.queries],
    };
  } catch (error) {
    if (error instanceof ToolingError) {
      return { ...report, ok: false, diagnostics: error.diagnostics };
    }
    throw error;
  }
}
