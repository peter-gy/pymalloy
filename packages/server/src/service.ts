import {
  checkSource,
  formatSource,
  parseSource,
  syntaxSource,
  compilerVersion,
} from "@malloy-runtime/compiler/tooling";
import { CompiledModel, ToolingError, type Job, type Fulfilled } from "@malloy-runtime/compiler";
import { connection, fields } from "@malloy-runtime/duckdb";
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
    if ("error" in answer) converted[key] = answer;
    else {
      try {
        converted[key] = { value: fields(answer.value) };
      } catch (error) {
        converted[key] = { error: error instanceof Error ? error.message : String(error) };
      }
    }
  }
  return { urls: answers.urls, schemas: converted };
}

export class CompilerService {
  private model?: CompiledModel;
  private active?: { step(answers?: Fulfilled): Response; close(): void };

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

  request(input: Request): Response {
    try {
      if (input.op === "step") {
        if (!this.active) throw new Error("Compiler has no pending request");
        return this.active.step(schemas(input.fulfilled));
      }
      this.active?.close();
      this.active = undefined;
      switch (input.op) {
        case "begin":
          if (this.model) throw new Error("Compiler already owns a model");
          return this.begin(
            CompiledModel.begin({ url: new URL(input.url), source: input.source, connection }),
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
          return this.begin(
            checkSource({ ...input, url: new URL(input.url), connection }),
            (report) => ({ kind: "check", report }),
          );
        case "format":
          return { kind: "format", ...formatSource(input.source) };
        case "parse":
          return { kind: "parse", report: parseSource(input.source, { url: new URL(input.url) }) };
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
    } catch (error) {
      this.active?.close();
      this.active = undefined;
      return {
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        diagnostics: error instanceof ToolingError ? error.diagnostics : [],
      };
    }
  }

  private current(): CompiledModel {
    if (!this.model) throw new Error("Compiler has no model");
    return this.model;
  }
}
