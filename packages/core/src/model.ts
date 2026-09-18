import { isMalloyText } from "./selection";
import type { Result as MalloyResult } from "@malloydata/malloy-interfaces";
import { type GivenValue, type PreparedQuery, type PreparedResult } from "@malloydata/malloy";
import { Job, type Task } from "./job";
import type { QueryDescriptor, QuerySelection, QueryOptions, DocumentOptions } from "./types";
import { loadSource, type LoadOptions, type LoadedSource, type PreparedSQL } from "./compile";
import { ToolingError, toolingError, plain } from "./diagnostics";
import { inspectModel, referenceAt, type Inspection, type ReferenceInfo } from "./inspect";
import type { NativeMetadata } from "./upstream";
import { compilerVersion, parseSource, type ParseReport, type SourcePosition } from "./tools";

export interface MarkdownCell {
  kind: "markdown";
  text: string;
}
export interface QueryCell {
  kind: "query";
  name: string;
  sql: string;
}
export type DocumentCell = MarkdownCell | QueryCell;

/** @title ModelSource */
export interface ModelSource {
  url: string;
  text: string;
  imports: Record<string, string>;
}

type QueryEntry =
  | { kind: "run" | "named"; query: PreparedQuery; result?: PreparedResult }
  | { kind: "view"; source: string; view: string; query?: PreparedQuery; result?: PreparedResult }
  | { kind: "sql"; prepared: PreparedSQL };

export class CompiledModel {
  private readonly entries = new Map<string, QueryEntry>();
  readonly queries: readonly QueryDescriptor[];

  private constructor(private readonly details: LoadedSource) {
    const { model, sqlQueries } = details;
    const add = (name: string, entry: QueryEntry) => {
      if (this.entries.has(name)) {
        throw new Error(
          `Ambiguous query selector '${name}'. Rename the conflicting query, source, or view.`,
        );
      }
      this.entries.set(name, entry);
    };
    const { named, unnamed } = model.queries();
    for (let index = 0; index < unnamed; index++)
      add(`run:${index}`, { kind: "run", query: model.getPreparedQueryByIndex(index) });
    for (const name of named)
      add(name, { kind: "named", query: model.getPreparedQueryByName(name) });
    for (const source of model.exportedExplores) {
      for (const field of source.structDef.fields) {
        if (field.type === "turtle" && field.accessModifier === undefined) {
          const view = field.as ?? field.name;
          add(`${source.name}.${view}`, { kind: "view", source: source.name, view });
        }
      }
    }
    for (const [index, prepared] of sqlQueries.entries())
      add(`sql:${index}`, { kind: "sql", prepared });
    this.queries = Object.freeze(
      [...this.entries].map(([name, entry]) => {
        const location =
          entry.kind === "run" || entry.kind === "named" ? entry.query.location : undefined;
        return {
          name,
          kind: entry.kind,
          location: location ? plain(location, details.locations) : null,
        };
      }),
    );
  }

  static begin(options: LoadOptions): Job<CompiledModel> {
    return new Job(CompiledModel.compileTask(options));
  }
  static *compileTask(options: LoadOptions): Task<CompiledModel> {
    return new CompiledModel(yield* loadSource(options));
  }

  source(): ModelSource {
    return {
      url: this.details.url.href,
      text: this.details.document,
      imports: Object.fromEntries(this.details.imports),
    };
  }

  inspect(): Inspection {
    return inspectModel(
      this.details.model,
      this.queries,
      this.details.locations,
      this.details.url,
      this.details.definition,
    );
  }

  reference(position: SourcePosition & { url?: URL }): ReferenceInfo {
    return referenceAt(
      this.details.model,
      this.details.translator,
      position,
      this.details.locations,
      this.details.url,
    );
  }

  prepare(
    selection?: QuerySelection,
    options: QueryOptions = {},
  ): Job<{ name: string; sql: string; line?: number; malloy?: MalloyResult }> {
    return new Job(this.prepareQuery(selection, structuredClone(options.givens)));
  }

  private *prepareQuery(
    selection?: QuerySelection,
    givens?: Record<string, GivenValue>,
  ): Task<{ name: string; sql: string; line?: number; malloy?: MalloyResult }> {
    try {
      return yield* this.compileQuery(selection, givens);
    } catch (error) {
      toolingError(error, this.details.locations);
    }
  }

  private *compileQuery(
    selection?: QuerySelection,
    givens?: Record<string, GivenValue>,
  ): Task<{ name: string; sql: string; line?: number; malloy?: MalloyResult }> {
    const { compile } = this.details;
    if (isMalloyText(selection)) {
      const extended = yield* compile({ base: this.details, source: selection.malloy });
      return this.output("query", extended.model.preparedQuery.getPreparedResult({ givens }));
    }
    const name =
      selection ??
      [...this.entries].findLast(([, entry]) => entry.kind === "run")?.[0] ??
      (this.entries.size === 1 ? this.entries.keys().next().value : undefined);
    if (name === undefined) {
      throw new Error(
        `Choose a query from: ${this.queries.map((q) => q.name).join(", ") || "the model has no queries"}`,
      );
    }
    const entry = this.entries.get(name);
    if (!entry) {
      throw new Error(
        `Unknown query '${name}'. Choose from: ${this.queries.map((q) => q.name).join(", ")}`,
      );
    }
    if (entry.kind === "sql") {
      const { prepared } = entry;
      if (prepared.connection !== this.details.connection.name)
        throw new Error(`SQL cell '${name}' requires the session connection`);
      let sql = prepared.parts[0];
      for (const [index, query] of prepared.queries.entries()) {
        sql += `(${query.getPreparedResult({ givens }).sql})${prepared.parts[index + 1]}`;
      }
      return { name, sql, line: prepared.line };
    }
    let query: PreparedQuery;
    if (entry.kind === "view") {
      if (!entry.query) {
        const quote = (value: string) => "`" + value.replaceAll("`", "\\`") + "`";
        const extended = yield* compile({
          base: this.details,
          source: `run: ${quote(entry.source)} -> ${quote(entry.view)}`,
        });
        entry.query = extended.model.preparedQuery;
      }
      query = entry.query;
    } else query = entry.query;
    // Like Malloy's QueryMaterializer, retain the default compilation, never parameter variants.
    const result =
      givens && Object.keys(givens).length
        ? query.getPreparedResult({ givens })
        : (entry.result ??= query.getPreparedResult());
    return this.output(name, result, query.location?.range.start.line);
  }

  private output(name: string, result: PreparedResult, line?: number) {
    if (result.connectionName !== this.details.connection.name)
      throw new Error(`Query '${name}' requires the session connection`);
    let metadata: MalloyResult | undefined;
    return {
      name,
      sql: result.sql,
      line,
      get malloy() {
        return (metadata ??= result.toStableResult());
      },
    };
  }

  defaultQueries(): string[] {
    const entries = [...this.entries];
    const preferred =
      entries.find(([, entry]) => entry.kind === "run" || entry.kind === "named")?.[1].kind ??
      "view";
    return entries
      .filter(([, entry]) =>
        this.details.statements
          ? entry.kind === "run" || entry.kind === "sql"
          : entry.kind === preferred,
      )
      .map(([name]) => name);
  }

  document(options: DocumentOptions = {}): Job<DocumentCell[]> {
    if (options.all && options.queries !== undefined)
      throw new Error("Choose query names or all: true");
    return new Job(this.documentCells(structuredClone(options)));
  }

  private *documentCells(options: DocumentOptions): Task<DocumentCell[]> {
    const { model, statements } = this.details;
    const { givens } = options;
    const selected = options.all
      ? this.queries.map((q) => q.name)
      : (options.queries ?? this.defaultQueries());
    const compiled = [];
    for (const selector of selected) compiled.push(yield* this.prepareQuery(selector, givens));
    const cells: DocumentCell[] = [];
    if (statements && !options.queries?.length && !options.all) {
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

/** @title CheckOptions */
export interface CheckOptions extends LoadOptions {
  position?: SourcePosition;
  syntaxOnly?: boolean;
}

/** @title CheckReport */
export interface CheckReport extends ParseReport {
  ok: boolean;
  compilerVersion: string;
  model: NativeMetadata;
  queries: QueryDescriptor[];
}

export function checkSource(options: CheckOptions): Job<CheckReport> {
  return new Job(checkTask(options));
}
function* checkTask(options: CheckOptions): Task<CheckReport> {
  let source = options.source;
  if (source === undefined) {
    const answer = (yield { urls: [options.url.href], schemas: [] }).urls[options.url.href];
    if (!answer || "error" in answer)
      throw new Error(answer && "error" in answer ? answer.error : "Missing source");
    source = answer.value;
  }
  const parsed = parseSource(source, options);
  const report = {
    ...parsed,
    ok: !parsed.diagnostics.some((problem) => problem.severity === "error"),
    compilerVersion: compilerVersion,
    model: { model: null, sources: [], annotations: [] },
    queries: [],
  };
  if (options.syntaxOnly || !report.ok) return report;
  try {
    const compiled = yield* CompiledModel.compileTask({ ...options, source });
    const inspection = compiled.inspect();
    return {
      ...report,
      ok: true,
      diagnostics: inspection.diagnostics,
      model: inspection.model,
      queries: [...compiled.queries],
    };
  } catch (error) {
    if (error instanceof ToolingError) {
      return { ...report, ok: false, diagnostics: error.diagnostics };
    }
    throw error;
  }
}
