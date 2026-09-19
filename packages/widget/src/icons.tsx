import * as stylex from "@stylexjs/stylex";

const paths = {
  check: "m5 12 4 4L19 6",
  run: "m8 4 12 8-12 8z",
  source: "M4 5h16v14H4zM4 9h16M9 9v10",
  code: "m8 6-6 6 6 6m8-12 6 6-6 6M14 4l-4 16",
  schema: "M5 3h6v5H5zM14 16h6v5h-6zM5 16h6v5H5zM8 8v5h9v3M8 13v3",
  context: "M12 17v-5m0-5v1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  result: "M4 4h16v16H4zM4 10h16M10 10v10M4 15h16",
  issue: "M12 8v5m0 3v1M12 3 2 21h20z",
  measure: "M18 5H6l7 7-7 7h12",
  calculate: "M7 20h2c2 0 2-4 3-8s1-8 3-8h2M7 10h10",
  cross: "M3 5v14m18-14v14M3 9h4m-4 6h4m10-6h4m-4 6h4m-11-4 4 4m0-4-4 4",
  number: "m9 4-3 16M18 4l-3 16M4 9h16M3 15h16",
  string: "m4 18 5-12 5 12M6 14h6M20 18v-7m0 1c-5-3-7 7-2 6l2-1",
  boolean: "M8 7h8a5 5 0 0 1 0 10H8A5 5 0 0 1 8 7M8 10v4",
  date: "M5 5h14v15H5zM5 10h14M8 3v4m8-4v4M8 14h3",
  array: "M8 4H4v16h4m8-16h4v16h-4M8 12h1m3 0h1m3 0h1",
  record: "M8 3H6v6l-3 3 3 3v6h2m8-18h2v6l3 3-3 3v6h-2",
  join: "M4 12h16M4 8v8m16-8v8",
  many: "M4 12h16M4 8v8m12-8 4 4-4 4",
  view: "M3 4h13v10H3zM3 8h13m-8 6v6h13V10h-5",
  unknown: "M8 8a4 4 0 1 1 7 3l-3 2v2m0 3v1",
} as const;
export type IconKind = keyof typeof paths;

export function Icon({ kind, label }: { kind: IconKind; label?: string }) {
  return (
    <svg
      {...stylex.props(styles.icon)}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {label ? <title>{label}</title> : null}
      <path d={paths[kind]} />
    </svg>
  );
}
const styles = stylex.create({
  icon: { width: 17, height: 17, flexShrink: 0, verticalAlign: "middle" },
});
