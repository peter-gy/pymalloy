import { memo, useEffect, useRef } from "react";
import * as stylex from "@stylexjs/stylex";
import { MalloyRenderer } from "@malloydata/render";
import type { Cell, Result } from "@malloydata/malloy-interfaces";
import { colors, tokens } from "./tokens.stylex";

export default memo(function ResultView({ result }: { result: Result }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    return mountResult(host, result);
  }, [result]);
  return <div ref={container} {...stylex.props(stylesForResult.frame)} />;
});

function mountResult(host: HTMLDivElement, result: Result) {
  const document = host.ownerDocument;
  const css = document.createElement("style");
  const body = document.createElement("div");
  host.append(css, body);
  const syncStyles = () => {
    const text = Array.from(document.head.querySelectorAll("style[data-malloy-viz]"))
      .map((node) => node.textContent)
      .join("\n");
    if (css.textContent !== text) css.textContent = text;
  };
  const describeTables = (element: Element) => {
    for (const [selector, role] of [
      [".malloy-table", "table"],
      [".table-row[data-index], .pinned-header-subrow", "row"],
      [".td", "cell"],
      [".th", "columnheader"],
    ]) {
      if (element.matches(selector)) element.setAttribute("role", role);
      for (const child of element.querySelectorAll(selector)) child.setAttribute("role", role);
    }
  };
  const styles = new MutationObserver(syncStyles);
  const tables = new MutationObserver((records) => {
    for (const record of records)
      for (const node of record.addedNodes) if (node instanceof Element) describeTables(node);
  });
  const viz = new MalloyRenderer().createViz();
  const cleanup = () => {
    tables.disconnect();
    styles.disconnect();
    viz.remove();
    css.remove();
    body.remove();
  };
  try {
    styles.observe(document.head, { childList: true });
    tables.observe(body, { childList: true, subtree: true });
    const data = result.data && restoreNumbers(result.data);
    viz.setResult(data === result.data ? result : { ...result, data });
    const metadata = viz.getMetadata();
    const fill =
      metadata && viz.getActivePlugin(metadata.getRootField().key)?.sizingStrategy === "fill";
    Object.assign(body, stylex.props(fill ? stylesForResult.fill : stylesForResult.table));
    viz.render(body);
    syncStyles();
    describeTables(body);
  } catch (error) {
    cleanup();
    throw error;
  }
  return cleanup;
}

const stylesForResult = stylex.create({
  frame: {
    "--malloy-theme--table-body-color": colors.text,
    "--malloy-theme--table-header-color": colors.muted,
    "--malloy-theme--table-background": colors.surface,
    "--malloy-theme--table-pinned-background": colors.surface,
    "--malloy-theme--table-border": `1px solid ${colors.border}`,
    "--malloy-theme--font-family": tokens.font,
    "--malloy-theme--background": colors.surface,
    overflowX: "auto",
    minWidth: 0,
  },
  table: { minWidth: 0 },
  fill: { height: 360, minWidth: 0 },
});

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
