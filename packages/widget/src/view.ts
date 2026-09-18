import type { RenderProps } from "@anywidget/types";
import { previewRows, type WidgetModel } from "./protocol";

function text(tag: string, value: string): HTMLElement {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

export function render({ model, el }: RenderProps<WidgetModel>): () => void {
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
  const sql = document.createElement("details");
  const code = document.createElement("pre");
  sql.append(text("summary", "SQL"), code);
  root.append(header, body, sql);
  el.append(root);
  const choose = () => {
    model.set("query", select.value || null);
    model.save_changes();
  };
  select.addEventListener("change", choose);
  const update = () => {
    const state = model.get("_state");
    if (!state) return;
    select.replaceChildren(
      new Option("Default query", ""),
      ...state.queries.map((name) => new Option(name, name)),
    );
    select.value = model.get("query") ?? "";
    select.disabled = state.status === "loading" || !state.queries.length;
    code.textContent = state.sql ?? "";
    sql.hidden = !state.sql;
    body.replaceChildren();
    root.setAttribute("aria-busy", String(state.status === "loading"));
    const messages = {
      idle: state.queries.length ? "Choose a query" : "Add a Malloy query to begin",
      loading: "Running query…",
      error: "Query failed",
      closed: "Closed",
      ready: `${state.rows.length} ${state.rows.length === 1 ? "row" : "rows"}`,
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
    const table = document.createElement("table");
    const caption = text("caption", "Query results");
    const head = table.createTHead().insertRow();
    for (const name of state.columns) {
      const cell = text("th", name);
      cell.setAttribute("scope", "col");
      head.append(cell);
    }
    table.prepend(caption);
    const rows = table.createTBody();
    for (const record of previewRows(state)) {
      const row = rows.insertRow();
      for (const name of state.columns) {
        const value = record[name];
        const cell = row.insertCell();
        // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Render the declared wire containers as expandable JSON.
        if (value !== null && typeof value === "object") {
          const detail = document.createElement("details");
          detail.append(
            text("summary", Array.isArray(value) ? `${value.length} items` : "Record"),
            text("pre", JSON.stringify(value, null, 2)),
          );
          cell.append(detail);
        } else cell.textContent = value === null ? "null" : String(value);
      }
    }
    body.append(table);
    if (state.rows.length > 100) body.append(text("p", `Showing 100 of ${state.rows.length} rows`));
  };
  model.on("change:_state", update);
  model.on("change:query", update);
  update();
  return () => {
    model.off("change:_state", update);
    model.off("change:query", update);
    select.removeEventListener("change", choose);
    root.remove();
  };
}
