import { ParseUtil } from "@malloydata/malloy-tag";
import type { ParserRuleContext } from "antlr4ts";
import type { NativeContext, NativeListener } from "./upstream";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";

/** Symbolic scalar syntax; Malloy remains responsible for typing and semantics. */
export type Scalar =
  | ScalarField
  | ScalarGiven
  | ScalarLiteral
  | ScalarUnary
  | ScalarBinary
  | ScalarCall
  | ScalarCast
  | ScalarNullTest
  | ScalarTruncate
  | ScalarFilter
  | ScalarCase
  | ScalarRaw;

export interface ScalarField {
  kind: "field";
  path: string[];
}
export interface ScalarGiven {
  kind: "given";
  name: string;
}
export interface ScalarLiteral {
  kind: "literal";
  type: "string" | "number" | "boolean" | "null" | "date" | "timestamp";
  value: string;
}
export interface ScalarUnary {
  kind: "unary";
  operator: "-" | "not";
  value: Scalar;
}
export interface ScalarBinary {
  kind: "binary";
  operator: string;
  left: Scalar;
  right: Scalar;
}
export interface ScalarCall {
  kind: "call";
  name: string;
  args: Scalar[];
  receiver: string[] | null;
}
export interface ScalarCast {
  kind: "cast";
  value: Scalar;
  type: string;
  safe: boolean;
}
export interface ScalarNullTest {
  kind: "null_test";
  value: Scalar;
  negated: boolean;
}
export interface ScalarTruncate {
  kind: "truncate";
  value: Scalar;
  unit: string;
}
export interface ScalarFilter {
  kind: "filter";
  value: Scalar;
  predicate: Scalar;
}
export interface ScalarCase {
  kind: "case";
  branches: Array<{ when: Scalar; then: Scalar }>;
  otherwise: Scalar;
}
export interface ScalarRaw {
  kind: "raw";
  code: string;
}

type PathContext = NativeContext<"enterFieldPath">;
type UnaryContext = ParserRuleContext & Pick<NativeContext<"enterExprMinus">, "fieldExpr">;
type BinaryContext = ParserRuleContext & Pick<NativeContext<"enterExprAddSub">, "fieldExpr">;
type CastContext = NativeContext<"enterExprCast"> | NativeContext<"enterExprSafeCast">;
type AggregateContext =
  | NativeContext<"enterExprAggregate">
  | NativeContext<"enterExprPathlessAggregate">;

const malloyTypes = new Set(["number", "string", "boolean", "date", "timestamp", "timestamptz"]);

export function identifierText(context: ParserRuleContext): string {
  const text = context.text;
  return text.startsWith("`") ? ParseUtil.parseString(text, "`") : text;
}

function containsRaw(value: Scalar): boolean {
  switch (value.kind) {
    case "raw":
      return true;
    case "field":
    case "given":
    case "literal":
      return false;
    case "unary":
    case "cast":
    case "null_test":
    case "truncate":
      return containsRaw(value.value);
    case "binary":
      return containsRaw(value.left) || containsRaw(value.right);
    case "call":
      return value.args.some(containsRaw);
    case "filter":
      return containsRaw(value.value) || containsRaw(value.predicate);
    case "case":
      return (
        value.branches.some((branch) => containsRaw(branch.when) || containsRaw(branch.then)) ||
        containsRaw(value.otherwise)
      );
  }
}

/** Project an upstream field-expression context without reparsing its text. */
export function scalarExpression(root: ParserRuleContext, characters: readonly string[]): Scalar {
  const values = new Map<ParserRuleContext, Scalar>();
  function raw(context: ParserRuleContext): ScalarRaw {
    return {
      kind: "raw",
      code: characters.slice(context.start.startIndex, context.stop!.stopIndex + 1).join(""),
    };
  }
  function value(context: ParserRuleContext): Scalar {
    return values.get(context) ?? raw(context);
  }
  function path(context: PathContext): string[] {
    return context.fieldName().map((name) => identifierText(name.id()));
  }
  function unary(context: UnaryContext, operator: ScalarUnary["operator"]): void {
    const operand = value(context.fieldExpr());
    values.set(
      context,
      operator === "-" &&
        operand.kind === "literal" &&
        operand.type === "number" &&
        !operand.value.startsWith("-")
        ? { ...operand, value: `-${operand.value}` }
        : { kind: "unary", operator, value: operand },
    );
  }
  function binary(context: BinaryContext, operator: string): void {
    const [left, right] = context.fieldExpr();
    values.set(context, { kind: "binary", operator, left: value(left), right: value(right) });
  }
  function cast(context: CastContext, safe: boolean): void {
    const target = context.malloyOrSQLType();
    const native = target.string()?.shortString();
    const malloy = target.malloyType();
    const type = native ? ParseUtil.parseString(native.text, native.text[0]) : malloy?.text;
    if (!type || (native ? malloyTypes.has(type) : !malloyTypes.has(type))) return;
    values.set(context, {
      kind: "cast",
      value: value(context.fieldExpr()),
      type,
      safe,
    });
  }
  function aggregate(context: AggregateContext, receiver: string[] | null): void {
    const argument = context.fieldExpr();
    values.set(context, {
      kind: "call",
      name: context.aggregate().text,
      args: argument ? [value(argument)] : [],
      receiver,
    });
  }

  const listener: NativeListener = {
    exitExprFieldPath: (context) => {
      values.set(context, { kind: "field", path: path(context.fieldPath()) });
    },
    exitExprGivenRef: (context) => {
      values.set(context, { kind: "given", name: context.GIVEN_REF().text.slice(1) });
    },
    exitExprString: (context) => {
      const string = context.string().shortString();
      if (string) {
        values.set(context, {
          kind: "literal",
          type: "string",
          value: ParseUtil.parseString(string.text, string.text[0]),
        });
      }
    },
    exitExprNumber: (context) => {
      values.set(context, {
        kind: "literal",
        type: "number",
        value: context.numericLiteral().text,
      });
    },
    exitExprBool: (context) => {
      values.set(context, {
        kind: "literal",
        type: "boolean",
        value: context.TRUE() ? "true" : "false",
      });
    },
    exitExprNULL: (context) => {
      values.set(context, { kind: "literal", type: "null", value: "null" });
    },
    exitLiteralDay: (context) => {
      const date = context.text.slice(1);
      const instant = new Date(`${date}T00:00:00Z`);
      if (
        date.startsWith("0000-") ||
        !Number.isFinite(instant.getTime()) ||
        instant.toISOString().slice(0, 10) !== date
      )
        return;
      values.set(context, { kind: "literal", type: "date", value: date });
    },
    exitExprTime: (context) => {
      values.set(context, value(context.dateLiteral()));
    },
    exitExprLiteral: (context) => {
      values.set(context, value(context.literal()));
    },
    exitExprExpr: (context) => {
      const inner = value(context.fieldExpr());
      if (inner.kind === "literal" && (inner.type === "date" || inner.type === "timestamp")) return;
      values.set(context, inner);
    },
    exitExprMinus: (context) => unary(context, "-"),
    exitExprNot: (context) => unary(context, "not"),
    exitExprAddSub: (context) => binary(context, context.PLUS() ? "+" : "-"),
    exitExprMulDiv: (context) =>
      binary(context, context.STAR() ? "*" : context.SLASH() ? "/" : "%"),
    exitExprCompare: (context) => binary(context, context.compareOp().text),
    exitExprLogicalAnd: (context) => binary(context, "and"),
    exitExprLogicalOr: (context) => binary(context, "or"),
    exitExprCoalesce: (context) => binary(context, "??"),
    exitExprCast: (context) => cast(context, false),
    exitExprSafeCast: (context) => cast(context, true),
    exitExprNullCheck: (context) => {
      values.set(context, {
        kind: "null_test",
        value: value(context.fieldExpr()),
        negated: Boolean(context.NOT()),
      });
    },
    exitExprTimeTrunc: (context) => {
      const unit = context.timeframe().text.toLowerCase();
      values.set(context, {
        kind: "truncate",
        value: value(context.fieldExpr()),
        unit: unit.endsWith("s") ? unit.slice(0, -1) : unit,
      });
    },
    exitExprFunc: (context) => {
      if (context.EXCLAM()) return;
      const name = context.id();
      if (name?.text.startsWith("`")) return;
      values.set(context, {
        kind: "call",
        name: name ? identifierText(name) : context.timeframe()!.text,
        args: (context.argumentList()?.fieldExpr() ?? []).map(value),
        receiver: null,
      });
    },
    exitExprPathlessAggregate: (context) => {
      if (!context.SOURCE_KW()) aggregate(context, null);
    },
    exitExprAggregate: (context) => aggregate(context, path(context.fieldPath())),
    exitExprAggFunc: (context) => {
      if (context.id().text.startsWith("`")) return;
      values.set(context, {
        kind: "call",
        name: identifierText(context.id()),
        args: (context.argumentList()?.fieldExpr() ?? []).map(value),
        receiver: path(context.fieldPath()),
      });
    },
    exitEveryRule: (context) => {
      if (context === root && !values.has(root)) values.set(root, raw(root));
    },
  };
  ParseTreeWalker.DEFAULT.walk(listener, root);
  const projected = values.get(root)!;
  // Temporal ranges and other opaque syntax depend on their original expression
  // context; regrouping just an unsupported child can change query semantics.
  return containsRaw(projected) ? raw(root) : projected;
}
