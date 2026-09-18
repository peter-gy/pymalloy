import { expect, test } from "vite-plus/test";
import { syntaxSource, type Scalar, type SyntaxNode } from "../src/tooling";
import { compile, drive } from "./host";

function isNode(part: string | SyntaxNode): part is SyntaxNode {
  return typeof part !== "string";
}

function text(node: SyntaxNode): string {
  if (node.type !== "syntax") return node.source;
  return node.parts.map((part) => (isNode(part) ? text(part) : part)).join("");
}

function children(node: SyntaxNode): SyntaxNode[] {
  return node.type === "syntax" ? node.parts.filter(isNode) : [];
}

function scopeChildren(node: SyntaxNode): SyntaxNode[] {
  return children(node).flatMap((child) =>
    child.type === "syntax" && child.kind === "expression"
      ? scopeChildren(child)
      : node.type === "syntax" &&
          node.kind === "document" &&
          child.type === "syntax" &&
          child.kind === "annotation"
        ? []
        : [child],
  );
}

function expression(node: SyntaxNode): SyntaxNode {
  const values = children(node).filter(
    (part) => part.type !== "syntax" || part.kind === "expression",
  );
  expect(values).toHaveLength(1);
  return values[0];
}

function name(node: SyntaxNode): string | null {
  return node.type === "syntax" ? node.name : null;
}

function scalarValue(node: SyntaxNode): Scalar {
  if (node.type !== "scalar") throw new Error("Expected scalar syntax");
  return node.scalar;
}

function replaceText(node: SyntaxNode, source: string): void {
  if (node.type === "scalar") {
    node.source = source;
    node.scalar = { kind: "raw", code: source };
  } else if (node.type === "syntax") {
    node.parts = [source];
  } else {
    node.source = source;
  }
}

test("syntax roundtrips unsupported constructs, annotations, Unicode, and CRLF exactly", () => {
  const source = [
    "// 😀 keep this comment",
    "##! experimental.givens",
    "given: threshold :: number is 2",
    "import {base is original} from 'base.malloy'",
    '#" A source',
    "source: `a\\`b`(p :: number is 1) is # note=kept",
    "  duckdb.sql(\"SELECT '😀' AS face\") extend {",
    "    dimension: `path\\\\name` is face",
    "    view: detail is {select: face}",
    "  }, other is base;",
    "export {other}",
    "run: other -> {select: *}",
    "// final comment",
    "",
  ].join("\r\n");
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  const [first, second] = scopeChildren(syntax);
  expect([name(first), name(second)]).toEqual(["a`b", "other"]);
  const rhs = expression(first);
  expect(text(rhs)).toMatch(/^duckdb\.sql/);
  expect(
    scopeChildren(rhs).map((node) => [node.type === "syntax" ? node.kind : "scalar", name(node)]),
  ).toEqual([
    ["field", "path\\name"],
    ["query", "detail"],
  ]);
  expect(text(expression(second))).toBe("base");
  expect(text(syntaxSource(""))).toBe("");
});

test("edits target one binding without crossing nested source and query scopes", async () => {
  const source = [
    "source: s is duckdb.sql('SELECT 42 AS value') extend {",
    "  dimension: doubled is value * 2",
    "  join_one: other is duckdb.sql('SELECT 42 AS value') extend {",
    "    dimension: doubled is value * 3",
    "  } on value = other.value",
    "  view: detail is {select: doubled}",
    "}",
    "query: result is s -> detail",
    "run: result",
  ].join("\n");
  const syntax = syntaxSource(source);
  const [namedSource, query] = scopeChildren(syntax);
  expect(query).toMatchObject({ kind: "query", name: "result" });
  const [field, join, view] = scopeChildren(expression(namedSource));
  expect([name(field), name(join), name(view)]).toEqual(["doubled", "other", "detail"]);
  expect(scopeChildren(expression(join)).map((node) => name(node))).toEqual(["doubled"]);
  replaceText(expression(field), "value * 4");
  const edited = text(syntax);
  expect(edited).toBe(source.replace("value * 2", "value * 4"));
  const url = new URL("memory://project/model.malloy");
  const fixture = {
    url,
    describe: async () => [{ name: "value", type: "INTEGER" }],
    readURL: async () => "",
  };
  const original = await compile({ ...fixture, source });
  const restored = await compile({ ...fixture, source: text(syntaxSource(source)) });
  expect((await drive(restored.prepare())).sql).toBe((await drive(original.prepare())).sql);
  expect((await drive((await compile({ ...fixture, source: edited })).prepare())).sql).toContain(
    "*4",
  );
});

test("malformed Malloy is rejected while plain model parsing is independent of its URL suffix", () => {
  expect(() => syntaxSource("source: incomplete is")).toThrowError(
    expect.objectContaining({
      name: "ToolingError",
      diagnostics: expect.arrayContaining([expect.objectContaining({ severity: "error" })]),
    }),
  );
  expect(text(syntaxSource("source: s is base", new URL("file:///model.malloynb")))).toBe(
    "source: s is base",
  );
});

test("named nests own their fields while anonymous nests and runs remain opaque", () => {
  const source = [
    "source: s is duckdb.sql('SELECT 1 AS value') extend {",
    "  view: detail is {",
    "    select: outer_value is value",
    "    nest: named is {select: inner_value is value}",
    "    nest: {select: anonymous_value is value}",
    "  }",
    "}",
    "run: s -> {select: run_value is value nest: hidden is {select: nested_value is value}}",
  ].join("\n");
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  const sources = scopeChildren(syntax);
  expect(sources.map((node) => name(node))).toEqual(["s"]);
  const [view] = scopeChildren(expression(sources[0]));
  const members = scopeChildren(expression(view));
  expect(
    members.map((node) => [node.type === "syntax" ? node.kind : "scalar", name(node)]),
  ).toEqual([
    ["field", "outer_value"],
    ["query", "named"],
  ]);
  expect(scopeChildren(expression(members[1])).map((node) => name(node))).toEqual(["inner_value"]);
  expect(scalarValue(expression(scopeChildren(expression(members[1]))[0]))).toEqual({
    kind: "field",
    path: ["value"],
  });
});

test("owned doc annotations are editable without changing shared tags, formatting, or literals", () => {
  const source = [
    '#" Shared statement documentation',
    'source: #" Before the name',
    '  orders #" Before is',
    '  is #" After is',
    "  duckdb.sql(\"SELECT '#(research) literal' AS value\") extend {",
    '    dimension: #" Field documentation',
    "      label is # currency=USD",
    "        value",
    "  }",
    'query: result is #" Query documentation',
    "  orders -> {select: label}",
  ].join("\r\n");
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  const [orders, query] = scopeChildren(syntax);
  const docs = scopeChildren(orders).filter(
    (part) => part.type === "syntax" && part.kind === "annotation",
  );
  expect(docs.map(text)).toEqual(['#" Before the name\r\n', '#" Before is\r\n', '#" After is\r\n']);
  const [field] = scopeChildren(expression(orders));
  expect(
    scopeChildren(field)
      .filter((part) => part.type === "syntax" && part.kind === "annotation")
      .map(text),
  ).toEqual(['#" Field documentation\r\n', "# currency=USD\r\n"]);
  expect(
    scopeChildren(query)
      .filter((part) => part.type === "syntax" && part.kind === "annotation")
      .map(text),
  ).toEqual(['#" Query documentation\r\n']);
  replaceText(docs[1], '#" Revised documentation\r\n');
  expect(text(syntax)).toBe(source.replace('#" Before is', '#" Revised documentation'));
  expect(text(expression(orders))).toContain("'#(research) literal'");
});

function scalar(authored: string): Scalar | undefined {
  const source = `source: s is duckdb.sql('SELECT 1') extend {dimension: x is ${authored}}`;
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  const [field] = scopeChildren(expression(scopeChildren(syntax)[0]));
  return scalarValue(expression(field));
}

test("scalar projections preserve precision, decoded identifiers, and aggregate receivers", () => {
  expect(scalar("-9007199254740993")).toEqual({
    kind: "literal",
    type: "number",
    value: "-9007199254740993",
  });
  expect(scalar("1.2300e-5")).toEqual({ kind: "literal", type: "number", value: "1.2300e-5" });
  expect(scalar("upper(`customer name`)")).toEqual({
    kind: "call",
    name: "upper",
    receiver: null,
    args: [{ kind: "field", path: ["customer name"] }],
  });
  expect(scalar("orders.amount.sum()")).toEqual({
    kind: "call",
    name: "sum",
    receiver: ["orders", "amount"],
    args: [],
  });
  expect(scalar("sum(amount + 1)")).toEqual({
    kind: "call",
    name: "sum",
    receiver: null,
    args: [
      {
        kind: "binary",
        operator: "+",
        left: { kind: "field", path: ["amount"] },
        right: { kind: "literal", type: "number", value: "1" },
      },
    ],
  });
  expect(scalar("$minimum")).toEqual({ kind: "given", name: "minimum" });
});

test("scalar projections distinguish casts, temporal truncation, and predicate operations", () => {
  expect(scalar("not (amount is null) and amount >= 0")).toMatchObject({
    kind: "binary",
    operator: "and",
    left: { kind: "unary", operator: "not", value: { kind: "null_test", negated: false } },
    right: { kind: "binary", operator: ">=" },
  });
  expect(scalar("amount ::: number")).toEqual({
    kind: "cast",
    type: "number",
    safe: true,
    value: { kind: "field", path: ["amount"] },
  });
  expect(scalar("CAST(amount AS 'INTEGER')")).toEqual({
    kind: "cast",
    type: "INTEGER",
    safe: false,
    value: { kind: "field", path: ["amount"] },
  });
  expect(scalar("(created).month")).toEqual({
    kind: "truncate",
    unit: "month",
    value: { kind: "field", path: ["created"] },
  });
  expect(scalar("@2025-03-14")).toEqual({ kind: "literal", type: "date", value: "2025-03-14" });
  expect(scalar("created = @2022-01-01")).toMatchObject({
    kind: "binary",
    right: { kind: "literal", type: "date", value: "2022-01-01" },
  });
  expect(scalar("coalesce(null, true, '😀')")).toMatchObject({
    kind: "call",
    name: "coalesce",
    args: [
      { kind: "literal", type: "null", value: "null" },
      { kind: "literal", type: "boolean", value: "true" },
      { kind: "literal", type: "string", value: "😀" },
    ],
  });
});

test("unsupported scalar syntax remains opaque rather than promoting supported descendants", () => {
  const unsupported = [
    "pick amount when active else 0",
    "amount.sum() {where: amount > 0}",
    "special!(amount)",
    "`upper`(name)",
    "orders.`max`(amount)",
    "r'prefix.*'",
    "@2025-03-14 10:00:00",
    "@0000-01-01",
    "@2025-02-30",
    "source.count()",
    "amount :: 'number'",
    "created = @2022",
    "created = (@2022-01-01)",
  ];
  for (const code of unsupported) expect(scalar(code)).toEqual({ kind: "raw", code });
  expect(scalar("special!(amount) + 1")).toEqual({
    kind: "raw",
    code: "special!(amount) + 1",
  });
});

test("temporal keyword spellings share the same symbolic truncation", async () => {
  expect(scalar("created.YEARS")).toEqual(scalar("created.year"));
  expect(scalar("created.Months")).toEqual(scalar("created.month"));
  expect(scalar("@2024-02-29")).toEqual({
    kind: "literal",
    type: "date",
    value: "2024-02-29",
  });
  const fixture = {
    url: new URL("memory://project/temporal.malloy"),
    source:
      "source: s is duckdb.sql('SELECT 1') extend {dimension: y is created.YEARS m is created.Months} run: s -> {select: y, m}",
    describe: async () => [{ name: "created", type: "TIMESTAMP" }],
    readURL: async () => "",
  };
  const authored = await compile(fixture);
  const normalized = await compile({
    ...fixture,
    source: fixture.source.replace(".YEARS", ".year").replace(".Months", ".month"),
  });
  expect((await drive(authored.prepare())).sql).toBe((await drive(normalized.prepare())).sql);
});

test("where, having, and join predicates retain their named owner and exact surrounding text", () => {
  const source = [
    "source: s is duckdb.sql('SELECT 1 AS value') extend {",
    "  where: value > 0, value < 100,",
    '  join_one: #" Joined source',
    "    other is duckdb.sql('SELECT 1 AS value') extend {where: value = 1}",
    "    on value = other.value",
    "  view: stats is {",
    "    aggregate: total is value.sum() {where: value > 0}",
    "    where: value > 10",
    "    having: total > 0, value.sum() {where: value > 0} > 0",
    "    nest: named is {aggregate: n is count() where: value > 20}",
    "    nest: {aggregate: n is count() where: value > 30}",
    "  }",
    "}",
    "run: s -> {select: value where: value > 40}",
  ].join("\r\n");
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  const [sourceWhere, join, view] = scopeChildren(expression(scopeChildren(syntax)[0]));
  expect(sourceWhere).toMatchObject({ type: "syntax", kind: "clause" });
  expect(children(sourceWhere).map(scalarValue)).toMatchObject([
    { kind: "binary", operator: ">" },
    { kind: "binary", operator: "<" },
  ]);
  const joinCondition = children(join).find(
    (node) => node.type === "syntax" && node.kind === "clause",
  )!;
  expect(scalarValue(expression(joinCondition))).toEqual({
    kind: "binary",
    operator: "=",
    left: { kind: "field", path: ["value"] },
    right: { kind: "field", path: ["other", "value"] },
  });
  expect(
    scopeChildren(expression(join)).map((node) => (node.type === "syntax" ? node.kind : "scalar")),
  ).toEqual(["clause"]);
  const members = scopeChildren(expression(view));
  expect(
    members.map((node) => [node.type === "syntax" ? node.kind : "scalar", name(node)]),
  ).toEqual([
    ["field", "total"],
    ["clause", null],
    ["clause", null],
    ["query", "named"],
  ]);
  expect(scalarValue(expression(members[0]))).toEqual({
    kind: "raw",
    code: "value.sum() {where: value > 0}",
  });
  expect(scalarValue(children(members[2])[1])).toEqual({
    kind: "raw",
    code: "value.sum() {where: value > 0} > 0",
  });
  expect(
    scopeChildren(expression(members[3])).map((node) =>
      node.type === "syntax" ? node.kind : "scalar",
    ),
  ).toEqual(["field", "clause"]);
  replaceText(children(sourceWhere)[0], "value > 1");
  expect(text(syntax)).toBe(source.replace("where: value > 0,", "where: value > 1,"));
});

test("native table leaves preserve file identity and authored spelling across scopes", () => {
  const source = [
    "// 😀 a code point before the table",
    "source: orders is duckdb.table('orders.parquet') extend {",
    "  join_one: other is warehouse.table('schema.other') on id = other.id",
    "}",
    'run: duckdb.table("inline.parquet") -> {select: *}',
  ].join("\r\n");
  const projected = syntaxSource(source);
  expect(text(projected)).toBe(source);
  function tables(node: SyntaxNode): SyntaxNode[] {
    return node.type === "table" ? [node] : children(node).flatMap(tables);
  }
  expect(tables(projected)).toEqual([
    {
      type: "table",
      connection: "duckdb",
      path: "orders.parquet",
      source: "duckdb.table('orders.parquet')",
    },
    {
      type: "table",
      connection: "warehouse",
      path: "schema.other",
      source: "warehouse.table('schema.other')",
    },
    {
      type: "table",
      connection: "duckdb",
      path: "inline.parquet",
      source: 'duckdb.table("inline.parquet")',
    },
  ]);
});

test("annotation routes preserve model flags, renderer tags, and app metadata", () => {
  const source = [
    "##! experimental.givens",
    "source: #(research) source=fixture",
    "  s is duckdb.sql('SELECT 1 value') extend {",
    '    measure: #" Revenue',
    "      total is # currency=USD",
    "      value.sum()",
    "  }",
  ].join("\n");
  const syntax = syntaxSource(source);
  expect(text(syntax)).toBe(source);
  function annotations(node: SyntaxNode): SyntaxNode[] {
    return node.type === "syntax" && node.kind === "annotation"
      ? [node]
      : children(node).flatMap(annotations);
  }
  expect(annotations(syntax).map(name)).toEqual(["!", "research", '"', ""]);
  const renderer = annotations(syntax)[3];
  replaceText(renderer, "# currency=EUR\n");
  expect(text(syntax)).toBe(source.replace("# currency=USD", "# currency=EUR"));
});
