import * as stylex from "@stylexjs/stylex";

const palette = {
  surface: "var(--jp-layout-color0, light-dark(#ffffff, #171b21))",
  inset: "light-dark(#f6f8fa, #1e242c)",
  text: "var(--jp-ui-font-color1, light-dark(#202b36, #e8edf2))",
  muted: "var(--jp-ui-font-color2, light-dark(#596775, #a5b3bf))",
  border: "var(--jp-border-color2, light-dark(#dbe2e8, #38444f))",
  accent: "light-dark(#305fbe, #9bbcff)",
  tint: "light-dark(#edf2fb, #23324e)",
  dimension: "light-dark(#426ca5, #8db8f4)",
  measure: "light-dark(#965521, #edb783)",
  view: "light-dark(#7659a8, #c0a6e7)",
  danger: "light-dark(#ad2738, #ff9ca9)",
};
export const colors = stylex.defineVars(palette);
export const theme = stylex.createTheme(colors, palette);
export const tokens = stylex.defineConsts({
  font: "var(--jp-ui-font-family, ui-sans-serif, system-ui, sans-serif)",
  mono: "var(--jp-code-font-family, ui-monospace, SFMono-Regular, Consolas, monospace)",
  radius: "10px",
  controlRadius: "6px",
  touch: "@media (pointer: coarse)",
  motion: "@media (prefers-reduced-motion: reduce)",
  hover: "@media (hover: hover) and (pointer: fine)",
});
