import { createRender, useModel } from "@anywidget/react";
import { Component, lazy, Suspense, useState, type ReactNode } from "react";
import * as stylex from "@stylexjs/stylex";
import type { ViewMessage } from "@pymalloy/protocol";
import type { RenderProps } from "@anywidget/types";
import { SchemaPanel, ContextPanel } from "./inspector";
import { Icon } from "./icons";
import { Tabs, type Tab, type TabId } from "./tabs";
import { Diagnostics, SourceCode } from "./parts";
import { useValue } from "./model";
import { colors, theme, tokens } from "./tokens.stylex";
import type { Definition, Input, NotebookInfo, State, WidgetModel } from "./protocol";

const ResultView = lazy(() => import("./result-view"));

interface ResultBoundaryState {
  error: Error | null;
}

class ResultBoundary extends Component<{ children: ReactNode }, ResultBoundaryState> {
  state: ResultBoundaryState = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    return this.state.error ? (
      <p role="alert" {...stylex.props(styles.failure)}>
        {this.state.error.message}
      </p>
    ) : (
      this.props.children
    );
  }
}

function MalloyView() {
  const definition = useValue("_definition");
  const input = useValue("_input");
  const published = useValue("_state");
  if (!definition || !input || input.definitionRevision !== definition.revision) return null;
  const info = definition.notebook;
  const state = published?.revision === input.revision ? published : null;
  const busy = state?.status === "loading";
  const executable = info.execution === "browser" || info.execution === "python";
  const status = statusLabel(state, input, info);
  return (
    <section
      {...stylex.props(theme, styles.root)}
      aria-label="Malloy query"
      aria-busy={busy}
      data-marimo-lens-label={info.kind}
      data-marimo-lens-detail={info.message ?? `Malloy ${info.kind.toLowerCase()}`}
    >
      <header {...stylex.props(styles.header)}>
        <div {...stylex.props(styles.identity)}>
          <Icon
            kind={
              info.kind === "Model"
                ? "source"
                : info.execution === "result"
                  ? "result"
                  : info.execution === "python"
                    ? "view"
                    : "code"
            }
          />
          <strong {...stylex.props(styles.title)}>{info.kind}</strong>
        </div>
        <span
          role="status"
          aria-live="polite"
          {...stylex.props(styles.status, state?.status === "error" && styles.errorStatus)}
        >
          {status}
        </span>
        {executable ? (
          <QueryControls state={state} input={input} execution={info.execution} />
        ) : null}
      </header>
      <InspectorTabs definition={definition} input={input} state={state} />
    </section>
  );
}

function statusLabel(state: State | null, input: Input, info: NotebookInfo): string {
  switch (state?.status) {
    case "ready": {
      const rows =
        state.result?.data?.kind === "array_cell" ? state.result.data.array_value.length : 0;
      return `${rows.toLocaleString()} ${rows === 1 ? "row" : "rows"}`;
    }
    case "error":
      return "Query failed";
    case "closed":
      return "Closed";
    case "loading":
      if (info.execution === "result") return "Loading result…";
      return input.action === "check" ? "Checking…" : "Running…";
    default:
      if (state?.inspection) return "Checked";
      return info.execution === "browser" || info.execution === "python" ? "Ready to inspect" : "";
  }
}

function QueryControls({
  state,
  input,
  execution,
}: {
  state: State | null;
  input: Input;
  execution: NotebookInfo["execution"];
}) {
  const model = useModel<WidgetModel>();
  const selection = useValue("query");
  const busy = state?.status === "loading";
  const request = (action: "check" | "run") => {
    model.set("_request", { revision: input.revision, action });
    model.save_changes();
  };
  return (
    <div {...stylex.props(styles.toolbar)}>
      {state && state.queries.length > 1 ? (
        <label {...stylex.props(styles.query)}>
          Query
          <select
            aria-label="Query"
            value={selection ?? ""}
            disabled={busy}
            {...stylex.props(styles.select)}
            onChange={(event) => {
              model.set("query", event.target.value || null);
              model.save_changes();
            }}
          >
            <option value="">
              {state.queries.some((query) => query.kind === "run") ? "Last run" : "Choose query"}
            </option>
            {state.queries.map((query) => (
              <option key={query.name} value={query.name}>
                {query.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div {...stylex.props(styles.actions)}>
        <button
          type="button"
          disabled={busy}
          {...stylex.props(styles.button)}
          onClick={() => request("check")}
        >
          <Icon kind="check" />
          Check
        </button>
        <button
          type="button"
          disabled={busy}
          {...stylex.props(styles.button, styles.primary)}
          onClick={() => request("run")}
        >
          <Icon kind="run" />
          {execution === "python" ? "Preview" : "Run"}
        </button>
      </div>
    </div>
  );
}

function describeTabs(info: NotebookInfo, input: Input, state: State | null) {
  const inspection = state?.inspection ?? null;
  const result = state?.result ?? null;
  const sql = info.execution === "result" ? info.source : result?.sql;
  const tabs: Tab[] = [];
  if (info.execution !== "result") tabs.push({ id: "source", label: "Source", icon: "code" });
  if (inspection || info.bindings.length || result)
    tabs.push({ id: "schema", label: "Schema", icon: "schema" });
  if (
    info.message ||
    info.annotations.length ||
    info.references.length ||
    info.inputs.length ||
    inspection?.givens.length
  )
    tabs.push({ id: "context", label: "Context", icon: "context" });
  if (result) tabs.push({ id: "result", label: "Result", icon: "result" });
  if (sql) tabs.push({ id: "sql", label: "SQL", icon: "code" });
  if (state?.error || state?.diagnostics.length)
    tabs.push({ id: "issues", label: "Issues", icon: "issue" });
  const preferred =
    state?.status === "error"
      ? "issues"
      : input.action === "check" && inspection
        ? "schema"
        : result
          ? "result"
          : tabs[0].id;
  return { tabs, preferred, sql };
}

function InspectorTabs({
  definition,
  input,
  state,
}: {
  definition: Definition;
  input: Input;
  state: State | null;
}) {
  const [selected, select] = useState<{ revision: number; tab: TabId } | null>(null);
  const info = definition.notebook;
  const { tabs, preferred, sql } = describeTabs(info, input, state);
  const active =
    selected?.revision === input.revision && tabs.some((tab) => tab.id === selected.tab)
      ? selected.tab
      : preferred;
  return (
    <Tabs tabs={tabs} active={active} onSelect={(tab) => select({ revision: input.revision, tab })}>
      <InspectorPanel active={active} info={info} state={state} sql={sql ?? ""} />
    </Tabs>
  );
}

function InspectorPanel({
  active,
  info,
  state,
  sql,
}: {
  active: TabId;
  info: NotebookInfo;
  state: State | null;
  sql: string;
}) {
  switch (active) {
    case "source":
      return <SourceCode source={info.source} />;
    case "schema":
      return (
        <SchemaPanel
          info={info}
          inspection={state?.inspection ?? null}
          output={state?.result?.schema}
        />
      );
    case "context":
      return <ContextPanel info={info} inspection={state?.inspection ?? null} />;
    case "sql":
      return <SourceCode source={sql} label="Compiled SQL" language="sql" />;
    case "issues":
      return state ? <Diagnostics diagnostics={state.diagnostics} error={state.error} /> : null;
    case "result":
      return state?.result ? (
        <ResultBoundary key={state.revision}>
          <Suspense fallback={<p {...stylex.props(styles.pending)}>Preparing result…</p>}>
            <ResultView result={state.result} />
          </Suspense>
        </ResultBoundary>
      ) : null;
  }
}

function StyledView() {
  const css = useValue("_css");
  return (
    <>
      <style>{css}</style>
      <MalloyView />
    </>
  );
}

const renderReact = createRender(StyledView);
export async function render(props: RenderProps<WidgetModel>) {
  const view = crypto.randomUUID();
  const { model } = props;
  const root = props.el.shadowRoot ?? props.el.attachShadow({ mode: "open" });
  const host = props.el.ownerDocument.createElement("div");
  root.append(host);
  const cleanup = await renderReact({ ...props, el: host });
  if (model.get("_transient"))
    model.send({ kind: "pymalloy-view", action: "mount", id: view } satisfies ViewMessage);
  return async () => {
    await cleanup?.();
    host.remove();
    if (model.get("_transient"))
      model.send({ kind: "pymalloy-view", action: "unmount", id: view } satisfies ViewMessage);
  };
}

const styles = stylex.create({
  root: {
    boxSizing: "border-box",
    colorScheme: "inherit",
    width: "100%",
    minWidth: 0,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: colors.border,
    borderRadius: tokens.radius,
    backgroundColor: colors.surface,
    color: colors.text,
    fontFamily: tokens.font,
    fontSize: 13,
    lineHeight: 1.5,
    overflow: "hidden",
    textAlign: "start",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: 16,
    flexWrap: "wrap",
  },
  identity: { display: "flex", alignItems: "center", gap: 10, minWidth: 0 },
  title: { fontSize: 14, fontWeight: 650, overflowWrap: "anywhere" },
  status: {
    fontSize: 11,
    color: colors.muted,
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  },
  errorStatus: { color: colors.danger },
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
    flex: "1 1 220px",
    justifyContent: "end",
    minWidth: 0,
  },
  query: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    minWidth: 0,
    flex: "1 1 180px",
    fontSize: 12,
    color: colors.muted,
  },
  select: {
    minWidth: 0,
    maxWidth: "100%",
    flex: "1 1 0%",
    minHeight: { default: 34, [tokens.touch]: 44 },
    fontFamily: "inherit",
    fontSize: 12,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: colors.border,
    borderRadius: tokens.controlRadius,
    paddingInline: 9,
    color: colors.text,
    backgroundColor: colors.surface,
    outlineWidth: 2,
    outlineStyle: "solid",
    outlineColor: { default: "transparent", ":focus-visible": colors.accent },
    outlineOffset: 2,
  },
  actions: { display: "flex", gap: 8, flexWrap: "wrap", marginInlineStart: "auto" },
  button: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    fontFamily: "inherit",
    fontSize: 12,
    fontWeight: 600,
    minHeight: { default: 34, [tokens.touch]: 44 },
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: colors.border,
    borderRadius: tokens.controlRadius,
    paddingInline: 12,
    backgroundColor: { default: colors.surface, [tokens.hover]: { ":hover": colors.inset } },
    color: colors.text,
    cursor: { default: "pointer", ":disabled": "wait" },
    outlineWidth: 2,
    outlineStyle: "solid",
    outlineColor: { default: "transparent", ":focus-visible": colors.accent },
    outlineOffset: 2,
    transform: { default: "none", ":active": { default: "scale(0.97)", [tokens.motion]: "none" } },
    opacity: { default: 1, ":disabled": 0.5 },
  },
  primary: { backgroundColor: colors.tint, color: colors.accent, borderColor: colors.tint },
  pending: { margin: 0, color: colors.muted, paddingBlock: 12 },
  failure: { margin: 18, color: colors.danger, whiteSpace: "pre-wrap" },
});
