import { useState } from "react";
import * as stylex from "@stylexjs/stylex";
import type { Inspection } from "@malloy-runtime/compiler";
import type { AtomicType, DimensionInfo, FieldInfo, Schema } from "@malloydata/malloy-interfaces";
import type { NotebookInfo } from "./protocol";
import { SourceCode } from "./parts";
import { Icon, type IconKind } from "./icons";
import { colors, tokens } from "./tokens.stylex";

type SchemaField = FieldInfo | DimensionInfo;

function typeLabel(type: AtomicType): string {
  if (type.kind === "array_type") return `array<${typeLabel(type.element_type)}>`;
  if (type.kind === "number_type") return type.subtype ?? "number";
  if (type.kind === "sql_native_type") return type.sql_type ?? "native";
  const name = type.kind.replace(/_type$/, "");
  return "timeframe" in type && type.timeframe ? `${name} · ${type.timeframe}` : name;
}
function typeIcon(type: AtomicType): IconKind {
  switch (type.kind) {
    case "number_type":
      return "number";
    case "string_type":
      return "string";
    case "boolean_type":
      return "boolean";
    case "date_type":
    case "timestamp_type":
    case "timestamptz_type":
      return "date";
    case "array_type":
      return "array";
    case "record_type":
    case "json_type":
      return "record";
    case "sql_native_type":
      return "source";
  }
}
function nestedFields(type: AtomicType): DimensionInfo[] {
  if (type.kind === "record_type") return type.fields;
  if (type.kind === "array_type") return nestedFields(type.element_type);
  return [];
}
function SchemaFields({ fields }: { fields: SchemaField[] }) {
  return (
    <ul {...stylex.props(styles.fields)}>
      {fields.map((field) => (
        <SchemaRow key={field.name} field={field} />
      ))}
    </ul>
  );
}
function describeField(field: SchemaField) {
  const kind = "kind" in field ? field.kind : "dimension";
  const children = "schema" in field ? field.schema.fields : nestedFields(field.type);
  const icon =
    kind === "measure"
      ? "measure"
      : kind === "calculate"
        ? "calculate"
        : "schema" in field
          ? field.kind === "view"
            ? "view"
            : field.relationship === "one"
              ? "join"
              : field.relationship === "cross"
                ? "cross"
                : "many"
          : typeIcon(field.type);
  const description =
    "schema" in field
      ? field.kind === "join"
        ? field.relationship
        : `${children.length} fields`
      : typeLabel(field.type);
  return { kind, children, icon, description };
}

function SchemaRow({ field }: { field: SchemaField }) {
  const { kind, children, icon, description } = describeField(field);
  return (
    <li>
      <div {...stylex.props(styles.row)}>
        <span {...stylex.props(styles[kind])}>
          <Icon kind={icon} label={kind} />
        </span>
        <span {...stylex.props(styles.name)}>{field.name}</span>
        <span {...stylex.props(styles.type)}>{description}</span>
      </div>
      {children.length ? (
        <div {...stylex.props(styles.nested)}>
          <SchemaFields fields={children} />
        </div>
      ) : null}
    </li>
  );
}

export function SchemaPanel({
  info,
  inspection,
  output,
}: {
  info: NotebookInfo;
  inspection: Inspection | null;
  output?: Schema;
}) {
  const [selected, setSelected] = useState("");
  const sources = inspection?.model.sources ?? [];
  const querySchemas = inspection?.model.model?.anonymous_queries ?? [];
  const source = sources.find((item) => item.name === selected) ?? sources[0];
  const schema = source?.schema ?? output ?? querySchemas[0]?.schema;
  if (schema)
    return (
      <div aria-label="Model schemas">
        {sources.length > 1 ? (
          <label {...stylex.props(styles.scope)}>
            Scope
            <select
              aria-label="Schema scope"
              value={source.name}
              onChange={(e) => setSelected(e.target.value)}
              {...stylex.props(styles.select)}
            >
              {sources.map((item) => (
                <option key={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
        ) : null}
        <SchemaFields fields={schema.fields} />
      </div>
    );
  return (
    <div>
      {info.bindings.length ? (
        <>
          <p {...stylex.props(styles.hint)}>Check to resolve field types.</p>
          <div {...stylex.props(styles.definitions)}>
            {info.bindings.map((binding) => (
              <div key={binding.name}>
                <div {...stylex.props(styles.row)}>
                  <Icon
                    kind={
                      binding.kind === "source"
                        ? "source"
                        : binding.kind === "query"
                          ? "view"
                          : "unknown"
                    }
                  />
                  <strong>{binding.name}</strong>
                </div>
                <SourceCode source={binding.source} label={`${binding.name} definition`} />
              </div>
            ))}
          </div>
        </>
      ) : (
        <p {...stylex.props(styles.hint)}>Run a query to inspect its output columns.</p>
      )}
    </div>
  );
}

export function ContextPanel({
  info,
  inspection,
}: {
  info: NotebookInfo;
  inspection: Inspection | null;
}) {
  return (
    <div {...stylex.props(styles.context)}>
      {info.message ? <p {...stylex.props(styles.hint)}>{info.message}</p> : null}
      {info.annotations.length ? (
        <section aria-label="Annotations">
          {info.annotations.map((annotation) => (
            <p key={annotation} {...stylex.props(styles.prose)}>
              {annotation}
            </p>
          ))}
        </section>
      ) : null}
      {info.references.length ? (
        <section>
          <h3 {...stylex.props(styles.label)}>References</h3>
          <p {...stylex.props(styles.prose)} aria-label="Referenced fields and sources">
            {info.references.join(" · ")}
          </p>
        </section>
      ) : null}
      {info.inputs.length ? (
        <section>
          <h3 {...stylex.props(styles.label)}>Inputs</h3>
          <ul {...stylex.props(styles.inputs)}>
            {info.inputs.map((input) => (
              <li key={input.name} {...stylex.props(styles.row)}>
                <Icon kind="source" />
                <span {...stylex.props(styles.name)}>{input.name}</span>
                <span {...stylex.props(styles.type)}>{input.rows.toLocaleString()} rows</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {inspection?.givens.length ? (
        <section>
          <h3 {...stylex.props(styles.label)}>Parameters</h3>
          <dl {...stylex.props(styles.inputs)}>
            {inspection.givens.map((given) => (
              <div key={given.name} {...stylex.props(styles.row)}>
                <dt {...stylex.props(styles.name)}>{given.name}</dt>
                <dd {...stylex.props(styles.type)}>
                  {given.type} · {given.required ? "required" : given.defaultText}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  );
}
const styles = stylex.create({
  fields: { listStyleType: "none", margin: 0, padding: 0, display: "grid", gap: 2 },
  row: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    minHeight: 34,
    paddingBlock: 3,
    minWidth: 0,
  },
  name: { fontWeight: 550, overflowWrap: "anywhere", minWidth: 0 },
  type: {
    color: colors.muted,
    fontSize: 11,
    margin: 0,
    marginInlineStart: "auto",
    textAlign: "end",
    overflowWrap: "anywhere",
  },
  dimension: { color: colors.dimension },
  calculate: { color: colors.view },
  measure: { color: colors.measure },
  join: { color: colors.accent },
  view: { color: colors.view },
  nested: {
    marginInlineStart: 8,
    paddingInlineStart: 18,
    borderInlineStartWidth: 1,
    borderInlineStartStyle: "solid",
    borderInlineStartColor: colors.border,
  },
  scope: {
    display: "flex",
    gap: 10,
    alignItems: "center",
    color: colors.muted,
    fontSize: 12,
    marginBottom: 12,
  },
  select: {
    fontFamily: "inherit",
    fontSize: 12,
    padding: 7,
    minHeight: { default: 34, [tokens.touch]: 44 },
    borderRadius: tokens.controlRadius,
    backgroundColor: colors.surface,
    color: colors.text,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: colors.border,
  },
  hint: { color: colors.muted, margin: 0, lineHeight: 1.6, fontSize: 12 },
  definitions: { display: "grid", gap: 16, marginTop: 12 },
  context: { display: "grid", gap: 20 },
  label: { margin: 0, marginBottom: 8, color: colors.muted, fontSize: 11, fontWeight: 600 },
  prose: { margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 },
  inputs: { listStyleType: "none", margin: 0, padding: 0 },
});
