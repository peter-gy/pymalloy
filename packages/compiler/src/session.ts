import {
  checkSource,
  formatSource,
  parseSource,
  syntaxSource,
  compilerVersion,
} from "@malloy-runtime/compiler/tooling";
import { ToolingError } from "@malloy-runtime/compiler";
import { CompiledModel, type Job, type Fulfilled } from "@malloy-runtime/compiler/jobs";
import { fields } from "@malloy-runtime/duckdb";
import {
  decodeGivens,
  type Request,
  type Response,
  type Output,
  type HostAnswers,
} from "@pymalloy/protocol";

function schemas(answers: HostAnswers): Fulfilled {
  const converted: Fulfilled["schemas"] = {};
  for (const [key, answer] of Object.entries(answers.schemas)) {
    if (answer.kind === "error") converted[key] = { error: answer.error };
    else {
      try {
        converted[key] = { value: fields(answer.value) };
      } catch (error) {
        converted[key] = { error: error instanceof Error ? error.message : String(error) };
      }
    }
  }
  return {
    urls: Object.fromEntries(
      Object.entries(answers.urls).map(([url, answer]) => [
        url,
        answer.kind === "error" ? { error: answer.error } : { value: answer.value },
      ]),
    ),
    schemas: converted,
  };
}

export class CompilerSession {
  private model?: CompiledModel;
  private active?: { step(answers?: Fulfilled): Response; close(): void };
  private closed = false;

  private begin<T>(job: Job<T>, finish: (result: T) => Output): Response {
    this.active = {
      step: (answers) => {
        const step = job.step(answers);
        if ("needs" in step) return { kind: "needs", needs: step.needs };
        this.active = undefined;
        return finish(step.result);
      },
      close: () => job.close(),
    };
    return this.active.step();
  }

  start(input: Request): Response {
    if (this.closed) return { kind: "failure", message: "Compiler is closed" };
    if (this.active) return { kind: "failure", message: "Compiler already has an active job" };
    return this.execute(() => {
      switch (input.op) {
        case "begin":
          if (this.model) throw new Error("Compiler already owns a model");
          return this.begin(
            CompiledModel.begin({
              url: new URL(input.url),
              source: input.source,
              documentKind: input.documentKind,
              connection: input.connection,
            }),
            (model) => {
              this.model = model;
              return {
                kind: "model",
                queries: model.queries,
                compilerVersion,
                source: model.source(),
              };
            },
          );
        case "check":
          return this.begin(checkSource({ ...input, url: new URL(input.url) }), (report) => ({
            kind: "check",
            report,
          }));
        case "format":
          return { kind: "format", ...formatSource(input.source) };
        case "parse":
          return {
            kind: "parse",
            report: parseSource(input.source, {
              url: new URL(input.url),
              documentKind: input.documentKind,
            }),
          };
        case "syntax":
          return { kind: "syntax", syntax: syntaxSource(input.source, new URL(input.url)) };
        case "source":
          return { kind: "source", source: this.current().source() };
        case "inspect": {
          const model = this.current();
          const inspection = model.inspect();
          if (input.position)
            Object.assign(
              inspection,
              model.reference({
                ...input.position,
                url: input.position.url ? new URL(input.position.url) : undefined,
              }),
            );
          return { kind: "inspection", inspection };
        }
        case "query":
          return this.begin(
            this.current().prepare(input.selection, { givens: decodeGivens(input.givens) }),
            ({ name, sql, line }) => ({ kind: "query", name, sql, line }),
          );
        case "document":
          return this.begin(
            this.current().document({
              queries: input.queries,
              all: input.all,
              givens: decodeGivens(input.givens),
            }),
            (cells) => ({ kind: "document", cells }),
          );
      }
    });
  }

  step(answers: HostAnswers): Response {
    if (this.closed) return { kind: "failure", message: "Compiler is closed" };
    if (!this.active) return { kind: "failure", message: "Compiler has no pending request" };
    return this.execute(() => this.active!.step(schemas(answers)));
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    const active = this.active;
    this.active = undefined;
    this.model = undefined;
    active?.close();
  }

  private execute(operation: () => Response): Response {
    try {
      return operation();
    } catch (error) {
      this.active?.close();
      this.active = undefined;
      const message = error instanceof Error ? error.message : String(error);
      return error instanceof ToolingError
        ? { kind: "error", message, diagnostics: error.diagnostics }
        : { kind: "failure", message };
    }
  }

  private current(): CompiledModel {
    if (!this.model) throw new Error("Compiler has no model");
    return this.model;
  }
}
