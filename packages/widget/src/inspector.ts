import type { Inspection } from "@malloy-runtime/compiler";
import type { Schema } from "@malloydata/malloy-interfaces";
import type { NotebookInfo } from "./protocol";
import { text } from "./dom";

function section(title: string, children: HTMLElement[]): HTMLElement {
  const details = document.createElement("details");
  details.append(text("summary", title), ...children);
  return details;
}

function schemaFields(schema: Schema): HTMLElement {
  const list = document.createElement("ul");
  for (const field of schema.fields) {
    const item = document.createElement("li");
    const type = "type" in field ? ` · ${field.type.kind.replace(/_type$/, "")}` : "";
    item.append(text("span", `${field.name} · ${field.kind}${type}`));
    if ("schema" in field) item.append(schemaFields(field.schema));
    list.append(item);
  }
  return list;
}

export function renderInspector(
  root: HTMLElement,
  info: NotebookInfo,
  inspection: Inspection | null,
): void {
  root.replaceChildren();
  if (info.message) root.append(text("p", info.message));
  const source = text("pre", info.source);
  source.setAttribute("aria-label", "Malloy source");
  source.tabIndex = 0;
  const sourceDetails = section(info.execution === "result" ? "Executed SQL" : "Malloy source", [
    source,
  ]);
  if (!info.execution || info.execution === "browser") sourceDetails.setAttribute("open", "");
  root.append(sourceDetails);
  if (info.bindings.length) {
    const list = document.createElement("div");
    for (const binding of info.bindings) {
      list.append(section(`${binding.name} · ${binding.kind}`, [text("pre", binding.source)]));
    }
    root.append(section("Named definitions", [list]));
  }
  if (info.references.length) {
    const refs = text("p", info.references.join(" · "));
    refs.setAttribute("aria-label", "Referenced fields and sources");
    root.append(section("References", [refs]));
  }
  if (info.annotations.length)
    root.append(
      section(
        "Annotations",
        info.annotations.map((value) => text("pre", value)),
      ),
    );
  if (info.inputs.length) {
    const list = document.createElement("ul");
    for (const input of info.inputs)
      list.append(text("li", `${input.name} · ${input.rows.toLocaleString()} captured rows`));
    root.append(section("Captured inputs", [list]));
  }
  if (inspection) {
    const schemas = document.createElement("div");
    schemas.setAttribute("aria-label", "Model schemas");
    for (const source of inspection.model.sources)
      schemas.append(section(source.name, [schemaFields(source.schema)]));
    root.append(section("Compiled schemas", [schemas]));
    if (inspection.givens.length) {
      const list = document.createElement("ul");
      for (const given of inspection.givens) {
        list.append(
          text(
            "li",
            `${given.name} · ${given.type} · ${given.required ? "required" : `default: ${given.defaultText}`}`,
          ),
        );
      }
      root.append(section("Parameters", [list]));
    }
  }
}
