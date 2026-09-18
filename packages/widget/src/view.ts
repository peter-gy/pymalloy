import type { Cell } from "@malloydata/malloy-interfaces";
import { MalloyRenderer } from "@malloydata/render";
import type { RenderProps } from "@anywidget/types";
import { type WidgetModel } from "./protocol";

function text(tag: string, value: string): HTMLElement {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

export function render({ model, el }: RenderProps<WidgetModel>): () => void {
  const viz = new MalloyRenderer().createViz();
  const root = document.createElement("section");
  root.className = "pymalloy-widget";
  root.setAttribute("aria-label", "Malloy query");
  const header = document.createElement("header");
  const label = text("label", "Query");
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Query");
  label.append(select);
  const status = text("span", "");
  status.setAttribute("role", "status");
  header.append(label, status);
  const body = document.createElement("div");
  body.className = "pymalloy-result";
  const styles = document.createElement("style");
  // Malloy registers styles in document.head. Notebook widgets can live in shadow roots.
  const syncStyles = () => {
    const css = Array.from(document.head.querySelectorAll("style[data-malloy-viz]"))
      .map((style) => style.textContent)
      .join("\n");
    if (styles.textContent !== css) styles.textContent = css;
  };
  const styleObserver = new MutationObserver((records) => {
    if (
      records.some((record) =>
        [...record.addedNodes, ...record.removedNodes].some(
          (node) => node instanceof HTMLStyleElement && node.hasAttribute("data-malloy-viz"),
        ),
      )
    )
      syncStyles();
  });
  styleObserver.observe(document.head, { childList: true });
  const roles = [
    [".malloy-table", "table"],
    [".table-row[data-index], .pinned-header-subrow", "row"],
    [".td", "cell"],
    [".th", "columnheader"],
  ] as const;
  const describeTables = (target: Element) => {
    for (const [selector, role] of roles) {
      if (target.matches(selector) && target.getAttribute("role") !== role)
        target.setAttribute("role", role);
      for (const element of target.querySelectorAll(selector))
        if (element.getAttribute("role") !== role) element.setAttribute("role", role);
    }
  };
  const tableObserver = new MutationObserver((records) => {
    for (const record of records)
      for (const node of record.addedNodes) if (node instanceof Element) describeTables(node);
  });
  tableObserver.observe(body, { childList: true, subtree: true });
  const sql = document.createElement("details");
  const code = document.createElement("pre");
  sql.append(text("summary", "SQL"), code);
  root.append(styles, header, body, sql);
  el.append(root);
  const choose = () => {
    model.set("query", select.value || null);
    model.save_changes();
  };
  select.addEventListener("change", choose);
  const updateSelection = () => {
    select.value = model.get("query") ?? "";
  };
  let queryNames: string[] = [];
  select.append(new Option("Default query", ""));
  const update = () => {
    const state = model.get("_state");
    if (!state || state.revision !== model.get("_input")?.revision) return;
    const names = state.queries.map((query) => query.name);
    if (
      names.length !== queryNames.length ||
      names.some((name, index) => name !== queryNames[index])
    ) {
      select.replaceChildren(
        new Option("Default query", ""),
        ...names.map((name) => new Option(name, name)),
      );
      queryNames = names;
    }
    updateSelection();
    select.disabled = state.status === "loading" || !state.queries.length;
    code.textContent = state.result?.sql ?? "";
    sql.hidden = !state.result?.sql;
    viz.remove();
    body.replaceChildren();
    body.style.height = "";
    root.setAttribute("aria-busy", String(state.status === "loading"));
    const messages = {
      idle: state.queries.length ? "Choose a query" : "Add a Malloy query to begin",
      loading: "Running query…",
      error: "Query failed",
      closed: "Closed",
      ready: `${state.result?.data?.kind === "array_cell" ? state.result.data.array_value.length : 0} ${state.result?.data?.kind === "array_cell" && state.result.data.array_value.length === 1 ? "row" : "rows"}`,
    };
    status.textContent = messages[state.status];
    if (state.error && !state.diagnostics.some((item) => item.severity === "error")) {
      const error = text("pre", state.error);
      error.setAttribute("role", "alert");
      body.append(error);
    }
    if (state.diagnostics.length) {
      const diagnostics = document.createElement("ul");
      diagnostics.className = "pymalloy-diagnostics";
      diagnostics.setAttribute("aria-label", "Compiler diagnostics");
      if (state.diagnostics.some((item) => item.severity === "error"))
        diagnostics.setAttribute("role", "alert");
      for (const diagnostic of state.diagnostics) {
        const item = document.createElement("li");
        item.append(text("p", diagnostic.message));
        const location = diagnostic.location;
        const origin = location
          ? `${location.url}:${location.range.start.line + 1}:${location.range.start.character + 1}`
          : null;
        item.append(
          text("small", [diagnostic.severity, diagnostic.code, origin].filter(Boolean).join(" · ")),
        );
        if (diagnostic.replacement !== null) {
          const replacement = document.createElement("details");
          replacement.append(
            text("summary", "Suggested replacement"),
            text("pre", diagnostic.replacement),
          );
          item.append(replacement);
        }
        diagnostics.append(item);
      }
      body.append(diagnostics);
    }
    if (state.error) return;
    if (state.status !== "ready") return;
    if (state.result) {
      const data = state.result.data && restoreNumbers(state.result.data);
      const result = data === state.result.data ? state.result : { ...state.result, data };
      viz.setResult(result);
      const metadata = viz.getMetadata();
      if (metadata && viz.getActivePlugin(metadata.getRootField().key)?.sizingStrategy === "fill")
        body.style.height = "360px";
      viz.render(body);
      syncStyles();
      describeTables(body);
    }
  };
  model.on("change:_state", update);
  model.on("change:query", updateSelection);
  update();
  return () => {
    model.off("change:_state", update);
    model.off("change:query", updateSelection);
    select.removeEventListener("change", choose);
    styleObserver.disconnect();
    tableObserver.disconnect();
    viz.remove();
    root.remove();
  };
}

function restoreNumbers<T extends Cell>(cell: T): T {
  if (
    cell.kind === "number_cell" &&
    cell.string_value &&
    ["NaN", "Infinity", "-Infinity"].includes(cell.string_value)
  )
    return { ...cell, number_value: Number(cell.string_value) };
  if (cell.kind !== "array_cell" && cell.kind !== "record_cell") return cell;
  const children = cell.kind === "array_cell" ? cell.array_value : cell.record_value;
  let changed: Cell[] | undefined;
  for (let i = 0; i < children.length; i++) {
    const value = restoreNumbers(children[i]);
    if (value !== children[i]) {
      changed ??= children.slice();
      changed[i] = value;
    }
  }
  if (!changed) return cell;
  return cell.kind === "array_cell"
    ? { ...cell, array_value: changed }
    : { ...cell, record_value: changed };
}
