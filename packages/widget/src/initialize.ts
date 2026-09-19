import { executeNative } from "./native";
import type { InitializeProps } from "@anywidget/types";
import type { Model, ModelSpec, SessionOptions, ToolingError } from "@malloy-runtime/browser";
import {
  givens,
  type Definition,
  type Diagnostic,
  type Input,
  type State,
  type WidgetModel,
} from "./protocol";
interface WidgetQuery {
  readonly queries: Model["queries"];
  inspect(): ReturnType<Model["inspect"]>;
  query(selection?: string): Pick<ReturnType<Model["query"]>, "run">;
  close(): void;
}
interface WidgetSession {
  readonly closed: boolean;
  model(spec: ModelSpec, options?: { signal?: AbortSignal }): Promise<WidgetQuery>;
  close(): Promise<void>;
}

export function initialize(
  createSession: (options: SessionOptions) => Promise<WidgetSession>,
  DiagnosticError: typeof ToolingError,
) {
  return ({ model }: InitializeProps<WidgetModel>) => {
    let closed = false;
    let generation = 0;
    let session: Promise<WidgetSession> | undefined;
    let retained: { revision: number; model: WidgetQuery } | undefined;
    let inspected: { revision: number; inspection: ReturnType<Model["inspect"]> } | undefined;
    let pending: { input: Input; definition: Definition; generation: number } | undefined;
    let running = false;
    const lifetime = new AbortController();
    let active: AbortController | undefined;
    const releaseModel = () => {
      retained?.model.close();
      retained = undefined;
    };
    const getSession = async () => {
      const pending = session;
      if (pending) {
        const current = await pending;
        if (!current.closed) return current;
        releaseModel();
        if (session === pending) session = undefined;
      }
      if (closed) throw new Error("Widget is closed");
      if (!session) {
        const opening = createSession({
          signal: lifetime.signal,
          bundles: model.get("_runtime") ?? undefined,
          connectionName: model.get("_definition")?.connectionName,
        });
        session = opening;
        void opening.catch(() => {
          if (session === opening) session = undefined;
        });
      }
      return session;
    };
    const execute = async ({
      input,
      definition,
      generation: current,
    }: NonNullable<typeof pending>) => {
      const operation = new AbortController();
      active = operation;
      const publish = (state: Omit<State, "revision">) => {
        if (closed || generation !== current) return;
        model.set("_state", { ...state, revision: input.revision });
        model.save_changes();
      };
      const empty = {
        queries: [],
        result: null,
        error: null,
        diagnostics: [],
        inspection: null,
      };
      const backend = definition.notebook.execution;
      if (backend !== "browser" || retained?.revision !== definition.revision) releaseModel();
      let queries = retained ? [...retained.model.queries] : definition.queries;
      let inspection = inspected?.revision === definition.revision ? inspected.inspection : null;
      let diagnostics: Diagnostic[] = inspection?.diagnostics ?? [];
      try {
        if (
          backend === null ||
          (input.action === "inspect" && backend !== "result") ||
          (backend === "browser" && !definition.source.trim())
        ) {
          publish({ ...empty, queries, inspection, diagnostics, status: "idle" });
          return;
        }
        publish({ ...empty, queries, inspection, diagnostics, status: "loading" });
        if (backend === "python" || backend === "result") {
          const response = await executeNative(model, input, operation.signal);
          if (closed || generation !== current) return;
          if ("inspection" in response) {
            inspection = response.inspection;
            inspected = { revision: definition.revision, inspection };
            publish({
              ...empty,
              queries,
              inspection,
              diagnostics: inspection.diagnostics,
              status: "idle",
            });
          } else {
            publish({
              ...empty,
              queries,
              inspection,
              diagnostics,
              result: response.result,
              status: "ready",
            });
          }
          return;
        }
        const runtime = await getSession();
        if (closed || generation !== current) return;
        if (retained?.revision !== definition.revision) {
          releaseModel();
          const files = Object.fromEntries(
            Object.entries(definition.files).map(([name, file]) => [
              name,
              ArrayBuffer.isView(file)
                ? new Uint8Array(file.buffer, file.byteOffset, file.byteLength)
                : file,
            ]),
          );
          const loaded = await runtime.model(
            definition.imports && definition.url
              ? {
                  source: {
                    documentKind: definition.documentKind,
                    text: definition.source,
                    url: definition.url,
                    imports: definition.imports,
                  },
                  files,
                }
              : {
                  text: definition.source,
                  url: definition.url ?? undefined,
                  documentKind: definition.documentKind,
                  files,
                },
            { signal: operation.signal },
          );
          if (closed || generation !== current) {
            loaded.close();
            return;
          }
          retained = { revision: definition.revision, model: loaded };
          inspection = loaded.inspect();
        }
        const loaded = retained.model;
        queries = [...loaded.queries];
        inspection ??= loaded.inspect();
        inspected = { revision: definition.revision, inspection };
        diagnostics = inspection.diagnostics;
        if (closed || generation !== current) return;
        if (
          input.action === "check" ||
          (!input.query &&
            (queries.length === 0 ||
              (queries.length > 1 && !queries.some((query) => query.kind === "run"))))
        ) {
          publish({ ...empty, queries, diagnostics, inspection, status: "idle" });
          return;
        }
        publish({ ...empty, queries, diagnostics, inspection, status: "loading" });
        const result = await loaded.query(input.query ?? undefined).run({
          givens: givens(input),
          signal: operation.signal,
        });
        publish({
          status: "ready",
          queries,
          result: result.malloy,
          error: null,
          diagnostics,
          inspection,
        });
      } catch (error) {
        if (error instanceof DiagnosticError) diagnostics = error.diagnostics;
        publish({
          ...empty,
          status: "error",
          queries,
          diagnostics,
          inspection,
          error: error instanceof Error ? error.message : String(error),
        });
      } finally {
        if (active === operation) active = undefined;
      }
    };
    const drain = async () => {
      running = true;
      try {
        while (pending && !closed) {
          const next = pending;
          pending = undefined;
          await execute(next);
        }
      } finally {
        running = false;
      }
    };
    const update = () => {
      const current = ++generation;
      active?.abort();
      pending = undefined;
      const input = model.get("_input");
      const definition = model.get("_definition");
      if (!input || !definition || input.definitionRevision !== definition.revision) return;
      pending = { input, definition, generation: current };
      if (!running) void drain();
    };
    model.on("change:_input", update);
    model.on("change:_definition", update);
    update();
    return async () => {
      closed = true;
      generation++;
      active?.abort();
      pending = undefined;
      releaseModel();
      lifetime.abort();
      model.off("change:_input", update);
      model.off("change:_definition", update);
      if (session) await (await session.catch(() => undefined))?.close();
    };
  };
}
