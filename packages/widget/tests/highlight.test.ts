import { expect, test } from "vite-plus/test";
import { highlight } from "../src/highlight";

test("Malloy embeds SQL and MOTLY while preserving authored token offsets", () => {
  const source =
    '#" Café 🌍\r\n# bar_chart x=region\r\nsource: orders is duckdb.sql("SELECT 42 AS amount")\r\n';
  const tokens = highlight(source, "malloy");
  for (const token of tokens) {
    expect(source.slice(token.offset, token.offset + token.content.length)).toBe(token.content);
  }
  const token = (content: string) => {
    const found = tokens.find((item) => item.content === content);
    expect(found, `Expected a distinct token for ${content}`).toBeDefined();
    return found!.variants;
  };
  const sql = highlight("SELECT 42", "sql");
  expect(token("SELECT")).toEqual(sql[0].variants);
  expect(token("SELECT").light.color).not.toBe(token("42").light.color);
  expect(token("x").light.color).not.toBe(token("region").light.color);
  expect(token("source").light.color).not.toBe(token("source").dark.color);
});
