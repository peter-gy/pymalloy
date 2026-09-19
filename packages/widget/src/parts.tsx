import * as stylex from "@stylexjs/stylex";
import type { Diagnostic } from "./protocol";
import { colors, tokens } from "./tokens.stylex";

export function SourceCode({
  source,
  label = "Malloy source",
}: {
  source: string;
  label?: string;
}) {
  return (
    <pre {...stylex.props(styles.code)} tabIndex={0} aria-label={label} dir="ltr">
      <code>{source}</code>
    </pre>
  );
}

export function Diagnostics({
  diagnostics,
  error,
}: {
  diagnostics: Diagnostic[];
  error: string | null;
}) {
  if (!diagnostics.length && !error) return null;
  const items = new Map(
    diagnostics.map((diagnostic) => [
      JSON.stringify([
        diagnostic.severity,
        diagnostic.code,
        diagnostic.message,
        diagnostic.location,
        diagnostic.replacement,
      ]),
      diagnostic,
    ]),
  );
  return (
    <div
      {...stylex.props(styles.diagnostics)}
      role={error || diagnostics.some((d) => d.severity === "error") ? "alert" : "status"}
    >
      {error && !diagnostics.some((d) => d.severity === "error") ? (
        <p {...stylex.props(styles.message)}>{error}</p>
      ) : null}
      {diagnostics.length ? (
        <ul {...stylex.props(styles.list)} aria-label="Compiler diagnostics">
          {[...items].map(([key, d]) => (
            <li key={key}>
              <p {...stylex.props(styles.message)}>{d.message}</p>
              <small>
                {[
                  d.severity,
                  d.code,
                  d.location
                    ? `${d.location.url}:${d.location.range.start.line + 1}:${d.location.range.start.character + 1}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
              {d.replacement !== null ? (
                <div {...stylex.props(styles.replacement)}>
                  <SourceCode source={d.replacement} label="Replacement" />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const styles = stylex.create({
  code: {
    margin: 0,
    padding: 14,
    borderRadius: tokens.controlRadius,
    fontFamily: tokens.mono,
    fontSize: 12,
    lineHeight: 1.65,
    overflowX: "auto",
    maxHeight: 360,
    backgroundColor: colors.inset,
    color: colors.text,
    tabSize: 2,
    outlineOffset: 2,
    outlineWidth: 2,
    outlineStyle: "solid",
    outlineColor: { default: "transparent", ":focus-visible": colors.accent },
  },
  diagnostics: {
    color: colors.danger,
    overflowWrap: "anywhere",
  },
  replacement: { marginTop: 12 },
  message: { marginBlock: 4, whiteSpace: "pre-wrap" },
  list: { margin: 0, paddingInlineStart: 18, display: "grid", gap: 12 },
});
