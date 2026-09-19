import { tableFromArrays, tableToIPC } from "apache-arrow";
import { afterEach, beforeEach, expect, test, vi } from "vite-plus/test";
import type { AnyModel } from "@anywidget/types";
import { ToolingError, type QueryOptions } from "@malloy-runtime/compiler";
import { initialize as initializeWith } from "../src/initialize";
import type {
  Definition,
  Diagnostic,
  Input,
  NotebookResponse,
  State,
  WidgetModel,
} from "../src/protocol";

const create = vi.fn<Parameters<typeof initializeWith>[0]>();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function definition(overrides: Partial<Definition> = {}): Definition {
  const source = overrides.source ?? "run: example";
  return {
    revision: 1,
    source,
    documentKind: "model",
    connectionName: "duckdb",
    files: {},
    queries: [],
    ...overrides,
    notebook: {
      kind: "Model",
      execution: "browser",
      message: null,
      bindings: [],
      references: [],
      annotations: [],
      inputs: [],
      ...overrides.notebook,
      source,
    },
  };
}

type Listener = Parameters<AnyModel<WidgetModel>["on"]>[1];

class Widget implements AnyModel<WidgetModel> {
  private values: WidgetModel;
  private listeners = new Map<string, Set<Listener>>();
  saved: State[] = [];
  widget_manager = {
    get_model: async () => {
      throw new Error("Unexpected widget lookup");
    },
  };
  send = vi.fn();

  constructor(input: Partial<Input> | null = {}, source: Partial<Definition> = {}) {
    this.values = {
      _css: "",
      query: input?.query ?? null,
      _input:
        input === null
          ? null
          : {
              revision: 1,
              definitionRevision: source.revision ?? 1,
              query: null,
              givens: {},
              action: "run",
              ...input,
            },
      _definition: input === null ? null : definition(source),
      _request: null,
      _transient: false,
      _runtime: null,
      _state: null,
    };
  }
  get<K extends keyof WidgetModel>(key: K): WidgetModel[K] {
    return this.values[key];
  }
  set<K extends keyof WidgetModel>(key: K, value: WidgetModel[K]): void {
    this.values[key] = value;
    for (const callback of this.listeners.get(`change:${key}`) ?? []) callback();
  }
  on(event: string, callback: Listener): void {
    const listeners = this.listeners.get(event) ?? new Set();
    listeners.add(callback);
    this.listeners.set(event, listeners);
  }
  off(event?: string | null, callback?: Listener | null): void {
    if (!event) this.listeners.clear();
    else if (callback) this.listeners.get(event)?.delete(callback);
    else this.listeners.delete(event);
  }
  reply(response: NotebookResponse, buffers: (ArrayBuffer | DataView)[] = []): void {
    const [[request]] = this.send.mock.calls.slice(-1);
    for (const callback of this.listeners.get("msg:custom") ?? [])
      callback({ kind: "pymalloy-response", id: request.id, response }, buffers);
  }
  save_changes(): void {
    const state = this.values._state;
    if (state) this.saved.push(structuredClone(state));
  }
  async request(action: "check" | "run"): Promise<void> {
    this.update({ action });
    await vi.waitFor(() =>
      expect(this.send.mock.lastCall?.[0]).toMatchObject({
        kind: "pymalloy-request",
        id: expect.any(String),
        input: this.get("_input"),
      }),
    );
  }
  update(input: Partial<Input> = {}, changes?: Partial<Definition>): void {
    const previous = this.get("_input") ?? {
      revision: 0,
      definitionRevision: 1,
      query: null,
      givens: {},
      action: "run",
    };
    const current = this.get("_definition");
    const definitionRevision = (current?.revision ?? 0) + Number(!current || changes !== undefined);
    if (!current || changes !== undefined)
      this.set("_definition", definition({ ...current, ...changes, revision: definitionRevision }));
    this.set("_input", {
      ...previous,
      ...input,
      revision: previous.revision + 1,
      definitionRevision,
    });
  }
}

function result(sql = "SELECT 1") {
  return {
    queries: ["run:0"],
    sql,
    columns: [{ name: "value", type: "INTEGER" }],
    rows: [{ value: 1 }],
    malloy: {
      connection_name: "duckdb",
      sql,
      schema: {
        fields: [
          { kind: "dimension" as const, name: "value", type: { kind: "number_type" as const } },
        ],
      },
      data: {
        kind: "array_cell" as const,
        array_value: [
          {
            kind: "record_cell" as const,
            record_value: [{ kind: "number_cell" as const, number_value: 1 }],
          },
        ],
      },
    },
  };
}
function model(queries = ["run:0"], diagnostics: Diagnostic[] = []) {
  const run = vi.fn(async (_options: QueryOptions = {}) => result());
  return {
    queries: queries.map((name) => ({
      name,
      kind: name.startsWith("run:") ? ("run" as const) : ("view" as const),
      location: null,
    })),
    query: vi.fn(() => ({ run })),
    inspect: vi.fn(() => ({
      diagnostics,
      model: { sources: [], model: null, annotations: [] },
      queries: [],
      givens: [],
      annotations: [],
      modelAnnotations: [],
      dependencies: [],
      imports: [],
    })),
    run,
    close: vi.fn(),
  };
}
function session(loaded = model()) {
  return { closed: false, model: vi.fn(async () => loaded), close: vi.fn(async () => {}) };
}
const disposals: Array<() => Promise<void>> = [];
async function initialize(widget: Widget): Promise<() => Promise<void>> {
  const dispose = initializeWith(create, (error) =>
    error instanceof ToolingError ? error.diagnostics : [],
  )({
    model: widget,
    signal: new AbortController().signal,
    experimental: { invoke: vi.fn() },
  });
  disposals.push(dispose);
  return dispose;
}

beforeEach(() => {
  create.mockReset();
});
afterEach(async () => {
  await Promise.all(disposals.splice(0).map((dispose) => dispose()));
});

test("a later input owns the published result while earlier work finishes", async () => {
  const pending = deferred<ReturnType<typeof result>>();
  const oldModel = model();
  oldModel.run.mockImplementation(() => pending.promise);
  const newModel = model();
  newModel.run.mockResolvedValue(result("SELECT 'new'"));
  const runtime = session(oldModel);
  runtime.model.mockResolvedValueOnce(oldModel).mockResolvedValueOnce(newModel);
  create.mockResolvedValue(runtime);
  const widget = new Widget();
  await initialize(widget);
  await vi.waitFor(() => expect(oldModel.run).toHaveBeenCalled());
  widget.update({}, { source: "run: newer" });
  widget.update({}, { source: "run: newest" });
  pending.resolve(result("SELECT 'old'"));
  await vi.waitFor(() => expect(widget.get("_state")?.result?.sql).toBe("SELECT 'new'"));
  await vi.waitFor(() => expect(oldModel.close).toHaveBeenCalled());
  expect(widget.get("_state")?.revision).toBe(3);
  expect(
    widget.saved.filter((state) => state.status === "ready").map((state) => state.result?.sql),
  ).toEqual(["SELECT 'new'"]);
  expect(runtime.model).toHaveBeenCalledTimes(2);
  expect(runtime.model).toHaveBeenLastCalledWith(
    {
      text: "run: newest",
      documentKind: "model",
      files: {},
      url: undefined,
    },
    { signal: expect.any(AbortSignal) },
  );
  expect(newModel.close).not.toHaveBeenCalled();
});

test("a new input replaces a session closed by worker failure", async () => {
  const failed = session();
  const replacement = session();
  create.mockResolvedValueOnce(failed).mockResolvedValueOnce(replacement);
  const widget = new Widget();
  await initialize(widget);
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  failed.closed = true;
  widget.update();
  await vi.waitFor(() => expect(replacement.model).toHaveBeenCalled());
  await vi.waitFor(() => expect(widget.get("_state")?.revision).toBe(2));
  expect(widget.get("_state")?.status).toBe("ready");
  expect(create).toHaveBeenCalledTimes(2);
});

test("selector and given updates reuse the model and coalesce pending work", async () => {
  const pending = deferred<ReturnType<typeof result>>();
  const loaded = model();
  loaded.run.mockImplementationOnce(() => pending.promise);
  const runtime = session(loaded);
  create.mockResolvedValue(runtime);
  const widget = new Widget();
  const dispose = await initialize(widget);
  await vi.waitFor(() => expect(loaded.run).toHaveBeenCalledTimes(1));
  widget.update({ givens: { threshold: { type: "number", value: 1 } } });
  widget.update({ query: "selected", givens: { threshold: { type: "number", value: 2 } } });
  pending.resolve(result());
  await vi.waitFor(() => expect(widget.get("_state")?.revision).toBe(3));
  expect(runtime.model).toHaveBeenCalledTimes(1);
  expect(loaded.run).toHaveBeenCalledTimes(2);
  expect(loaded.query).toHaveBeenLastCalledWith("selected");
  expect(loaded.run).toHaveBeenLastCalledWith({
    givens: { threshold: 2 },
    signal: expect.any(AbortSignal),
  });
  expect(
    widget.saved.filter((state) => state.status === "ready").map((state) => state.revision),
  ).toEqual([3]);
  await dispose();
  expect(loaded.close).toHaveBeenCalledTimes(1);
});

test("a definition can arrive after the input that references it", async () => {
  const runtime = session();
  create.mockResolvedValue(runtime);
  const widget = new Widget(null);
  await initialize(widget);
  expect(create).not.toHaveBeenCalled();
  expect(widget.saved).toEqual([]);
  widget.set("_input", {
    revision: 1,
    definitionRevision: 3,
    query: null,
    givens: {},
    action: "run",
  });
  widget.set("_definition", definition({ revision: 2, source: "run: obsolete" }));
  expect(create).not.toHaveBeenCalled();
  widget.set("_definition", definition({ revision: 3, source: "run: current" }));
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(runtime.model).toHaveBeenCalledExactlyOnceWith(
    {
      text: "run: current",
      documentKind: "model",
      files: {},
      url: undefined,
    },
    { signal: expect.any(AbortSignal) },
  );
});

test("cleanup aborts initialization and detaches input updates", async () => {
  let signal!: AbortSignal;
  create.mockImplementation((options) => {
    signal = options.signal!;
    return new Promise((_resolve, reject) =>
      signal.addEventListener("abort", () => reject(new Error("Aborted"))),
    );
  });
  const widget = new Widget();
  const dispose = await initialize(widget);
  await vi.waitFor(() => expect(create).toHaveBeenCalled());
  const before = widget.saved.length;
  await dispose();
  expect(signal.aborted).toBe(true);
  widget.update();
  expect(widget.saved).toHaveLength(before);
  expect(create).toHaveBeenCalledTimes(1);
});

test("query choices support selection and recovery after a failed query", async () => {
  const loaded = model(["orders.summary", "orders.detail"]);
  loaded.run.mockRejectedValueOnce(new Error("Invalid given"));
  create.mockResolvedValue(session(loaded));
  const widget = new Widget();
  await initialize(widget);
  await vi.waitFor(() =>
    expect(widget.get("_state")?.queries.map((q) => q.name)).toEqual([
      "orders.summary",
      "orders.detail",
    ]),
  );
  expect(widget.get("_state")?.status).toBe("idle");
  expect(loaded.run).not.toHaveBeenCalled();
  widget.update({ query: "orders.summary" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("error"));
  expect(widget.get("_state")?.queries.map((q) => q.name)).toEqual([
    "orders.summary",
    "orders.detail",
  ]);
  expect(widget.get("_state")?.error).toBe("Invalid given");
  widget.update({ query: "orders.detail" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(loaded.query).toHaveBeenLastCalledWith("orders.detail");
  expect(loaded.run).toHaveBeenLastCalledWith({ givens: {}, signal: expect.any(AbortSignal) });
  expect(widget.get("_state")?.result?.data).toEqual(result().malloy.data);
  expect(widget.get("_state")?.error).toBeNull();
});

test("source-only models stay idle until a query is added", async () => {
  const runtime = session(model([]));
  create.mockResolvedValue(runtime);
  const widget = new Widget({}, { source: "source: example is data" });
  await initialize(widget);
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("idle"));
  expect(widget.get("_state")?.queries.map((q) => q.name)).toEqual([]);
  runtime.model.mockResolvedValue(model());
  widget.update({}, { source: "run: example" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
});

test("model revisions publish warnings, located errors, and recovered results", async () => {
  const warning: Diagnostic = {
    code: "deprecated-syntax",
    severity: "warning",
    message: "Use the current source syntax",
    location: null,
    replacement: "source: orders",
    data: null,
    errorTag: null,
  };

  const diagnostic = {
    code: "source-or-query-not-found",
    severity: "error" as const,
    message: "Reference to undefined object 'missing_source'",
    location: {
      url: "https://pymalloy.local/model.malloy",
      range: { start: { line: 0, character: 5 }, end: { line: 0, character: 19 } },
    },
    replacement: null,
    data: { name: "missing_source" },
    errorTag: null,
  };
  const error = new ToolingError(diagnostic.message, [diagnostic]);
  const runtime = session();
  runtime.model
    .mockResolvedValueOnce(model(["run:0"], [warning]))
    .mockRejectedValueOnce(error)
    .mockResolvedValueOnce(model());
  create.mockResolvedValue(runtime);
  const widget = new Widget();
  await initialize(widget);
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(widget.get("_state")).toMatchObject({
    diagnostics: [warning],
    error: null,
    result: { sql: "SELECT 1" },
  });
  widget.update({}, { source: "run: missing_source" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("error"));
  expect(widget.get("_state")).toMatchObject({
    diagnostics: [diagnostic],
    error: diagnostic.message,
    result: null,
  });
  widget.update({}, { source: "run: recovered" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(widget.get("_state")).toMatchObject({
    diagnostics: [],
    error: null,
    result: { sql: "SELECT 1" },
  });
});

test("inspection-only cell output waits for an explicit compilation request", async () => {
  const runtime = session(model(["orders.by_region", "orders.detail"]));
  create.mockResolvedValue(runtime);
  const widget = new Widget({ action: "inspect" });
  await initialize(widget);
  expect(widget.get("_state")?.status).toBe("idle");
  expect(create).not.toHaveBeenCalled();
  widget.update({ action: "check" });
  await vi.waitFor(() => expect(widget.get("_state")?.inspection?.model.sources).toEqual([]));
  expect(runtime.model).toHaveBeenCalledTimes(1);
  expect(widget.get("_state")?.result).toBeNull();
  widget.update({ query: "orders.by_region", action: "inspect" });
  await vi.waitFor(() =>
    expect(widget.get("_state")?.queries.map((query) => query.name)).toEqual([
      "orders.by_region",
      "orders.detail",
    ]),
  );
  widget.update({ action: "run" });
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(runtime.model).toHaveBeenCalledTimes(1);
});

test("native previews retain inspection, recover from malformed replies, and settle on close", async () => {
  const widget = new Widget({ action: "inspect" });
  const definition = widget.get("_definition");
  if (!definition) throw new Error("Test requires a definition");
  widget.set("_definition", {
    ...definition,
    notebook: { ...definition.notebook, execution: "python" },
  });
  const close = await initialize(widget);
  expect(create).not.toHaveBeenCalled();
  expect(widget.send).not.toHaveBeenCalled();
  await widget.request("check");
  const inspection = model().inspect();
  widget.reply({ kind: "inspection", inspection });
  await vi.waitFor(() => expect(widget.get("_state")?.inspection).toEqual(inspection));
  await widget.request("run");
  const result: NotebookResponse = {
    kind: "result",
    sql: "SELECT 42 AS answer",
    columns: [{ name: "answer", type: "DOUBLE" }],
    connectionName: "duckdb",
  };
  widget.reply(result);
  await vi.waitFor(() => expect(widget.get("_state")?.error).toContain("Arrow buffer"));
  await widget.request("run");
  const bytes = tableToIPC(tableFromArrays({ answer: [42] }));
  widget.reply(result, [new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)]);
  await vi.waitFor(() => expect(widget.get("_state")?.status).toBe("ready"));
  expect(widget.get("_state")?.inspection).toEqual(inspection);
  expect(widget.get("_state")?.result).toMatchObject({
    sql: "SELECT 42 AS answer",
    data: {
      kind: "array_cell",
      array_value: [
        { kind: "record_cell", record_value: [{ kind: "number_cell", number_value: 42 }] },
      ],
    },
  });
  await widget.request("run");
  await close();
  const saved = widget.get("_state");
  widget.reply({ kind: "error", message: "late failure", diagnostics: [] });
  expect(widget.get("_state")).toBe(saved);
});
