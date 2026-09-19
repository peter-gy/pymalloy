import { routeOf } from "@malloydata/malloy";
import { ParseUtil } from "@malloydata/malloy-tag";
import type { ParserRuleContext } from "antlr4ts";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";
import { diagnostics, ToolingError } from "./diagnostics";
import { identifierText, scalarExpression, type Scalar } from "./scalar";
import { tableReferences } from "./tables";
import { defaultSourceURL } from "./source";
import { createTranslator, parseTree, type NativeContext, type NativeListener } from "./upstream";

/** Lossless authored syntax. Strings retain all syntax outside editable bindings. */
export type SyntaxNode = ConcreteSyntax | ScalarSyntax | TableSyntax;

/** A native table source, retaining its exact spelling and resolved reference. */
/** @public */
export type SyntaxKind =
  | "document"
  | "source"
  | "query"
  | "field"
  | "expression"
  | "annotation"
  | "clause";

export interface TableSyntax {
  type: "table";
  source: string;
  connection: string;
  path: string;
}

export interface ConcreteSyntax {
  type: "syntax";
  kind: SyntaxKind;
  name: string | null;
  parts: Array<string | SyntaxNode>;
  operation: SyntaxOperation | null;
}

/** Constructor structure identified by Malloy's parser, independently of spelling. */
export type SyntaxOperationKind =
  | "source"
  | "query"
  | "block"
  | "extend"
  | "pipe"
  | "ref"
  | "sql"
  | "dimension"
  | "measure"
  | "view"
  | "nest"
  | "group_by"
  | "select"
  | "aggregate"
  | "where"
  | "having"
  | "limit"
  | "primary_key"
  | "order_by"
  | "asc"
  | "desc";

export interface SyntaxOperation {
  kind: SyntaxOperationKind;
  arguments: string[];
}

/** A scalar operation tree paired with its original authored spelling. */
export interface ScalarSyntax {
  type: "scalar";
  source: string;
  scalar: Scalar;
}

type NamedContext = ParserRuleContext & Pick<NativeContext<"enterSourceNameDef">, "id">;
type JoinContext = NativeContext<"enterJoinOn"> | NativeContext<"enterJoinWith">;
type FilterContext = NativeContext<"enterWhereStatement"> | NativeContext<"enterHavingStatement">;

interface Span {
  kind: ConcreteSyntax["kind"];
  name: string | null;
  start: number;
  end: number;
  children: Span[];
  operation?: SyntaxOperation;
}

/** Parse plain Malloy without schema discovery and preserve untouched text exactly. */
export function syntaxSource(source: string, url = new URL(defaultSourceURL)): SyntaxNode {
  const translator = createTranslator(url.href, url.href, {
    urls: { [url.href]: source },
  });
  const parsed = parseTree(translator);
  const problems = diagnostics(translator.problems());
  if (!parsed || problems.some((problem) => problem.severity === "error")) {
    throw new ToolingError("Cannot edit malformed Malloy syntax", problems);
  }

  // ANTLR's CodePointCharStream uses Unicode codepoint offsets, including for CRLF.
  const characters = Array.from(source);
  const root: Span = {
    kind: "document",
    name: null,
    start: 0,
    end: characters.length,
    children: [],
  };
  const scopes = [{ binding: root, expression: root }];
  const bindings = new Set<ParserRuleContext>();
  const opaque = new Set<ParserRuleContext>();
  const scalarExpressions = new Map<Span, ParserRuleContext>();
  const tables = new Map<Span, TableSyntax>();
  const operations: Span[] = [];
  const scalars = new Map<Span, Scalar>();
  const nests: Array<{ span: Span | undefined; expected: number; named: number }> = [];

  function operation(
    context: ParserRuleContext,
    kind: SyntaxOperation["kind"],
    args: string[] = [],
  ): Span | undefined {
    if (opaque.size || scalarExpressions.has(scopes[scopes.length - 1].expression)) return;
    const span: Span = {
      kind: "expression",
      name: null,
      start: context.start.startIndex,
      end: context.stop!.stopIndex + 1,
      children: [],
      operation: { kind, arguments: args },
    };
    operations.push(span);
    return span;
  }

  function fieldEntry(
    context: NativeContext<"enterQueryFieldEntry"> | NativeContext<"enterCollectionMember">,
  ): boolean {
    const reference = context.taggedRef();
    return Boolean(
      context.fieldDef() ||
      (reference && !reference.refExpr() && !reference.tags().annotation().length),
    );
  }

  function statement(context: ParserRuleContext): void {
    if (!opaque.size && !scalarExpressions.has(scopes[scopes.length - 1].expression))
      operations.push({
        kind: "expression",
        name: null,
        start: context.start.startIndex,
        end: context.stop!.stopIndex + 1,
        children: [],
      });
  }

  function bind(
    context: ParserRuleContext,
    kind: "source" | "query" | "field",
    identifier: NamedContext,
    expression: ParserRuleContext,
  ): Span | undefined {
    if (opaque.size || (scopes.length === 1 && kind === "field")) return;
    const owner = scopes[scopes.length - 1].expression;
    const start = context.start.startIndex;
    const end = context.stop!.stopIndex + 1;
    if (start < owner.start || end > owner.end) return;
    const name = identifierText(identifier.id());
    const rhs: Span = {
      kind: "expression",
      name: null,
      start: expression.start.startIndex,
      end: expression.stop!.stopIndex + 1,
      children: [],
    };
    const binding = { kind, name, start, end, children: [rhs] };
    if (kind === "field") scalarExpressions.set(rhs, expression);
    owner.children.push(binding);
    scopes.push({ binding, expression: rhs });
    bindings.add(context);
    return binding;
  }

  function join(context: JoinContext): Span | undefined {
    const from = context.joinFrom();
    const expression = from.isExplore()?.sqExpr();
    if (expression) return bind(context, "source", from.joinNameDef(), expression);
  }

  function clause(owner: Span, context: ParserRuleContext, predicates: ParserRuleContext[]): void {
    owner.children.push({
      kind: "clause",
      name: null,
      start: context.start.startIndex,
      end: context.stop!.stopIndex + 1,
      children: predicates.map((predicate) => {
        const span: Span = {
          kind: "expression",
          name: null,
          start: predicate.start.startIndex,
          end: predicate.stop!.stopIndex + 1,
          children: [],
        };
        scalarExpressions.set(span, predicate);
        return span;
      }),
    });
  }

  function filter(context: FilterContext): void {
    if (opaque.size || scopes.length === 1) return;
    const owner = scopes[scopes.length - 1].expression;
    if (
      scalarExpressions.has(owner) ||
      context.start.startIndex < owner.start ||
      context.stop!.stopIndex + 1 > owner.end
    )
      return;
    clause(owner, context, context.filterClauseList().fieldExpr());
    opaque.add(context);
  }

  function annotation(context: ParserRuleContext): void {
    if (opaque.size) return;
    const { binding, expression } = scopes[scopes.length - 1];
    const start = context.start.startIndex;
    const end = context.stop!.stopIndex + 1;
    if (scopes.length > 1 && (start < binding.start || end > expression.start)) return;
    // Shared statement annotations belong to the document, not a named binding.
    const token = characters.slice(start, end).join("");
    const route = routeOf({ value: token });
    if (route === undefined) return;
    binding.children.push({
      kind: "annotation",
      name: route,
      start,
      end,
      children: [],
    });
  }

  const listener: NativeListener = {
    enterDefineSourceStatement: (context) => {
      if (
        !context.tags().annotation().length &&
        context
          .sourcePropertyList()
          .sourceDefinition()
          .every((source) => !source.sourceParameters())
      )
        operation(context, "source");
    },
    enterTopLevelQueryDefs: (context) => {
      if (!context.tags().annotation().length) operation(context, "query");
    },
    enterExploreProperties: (context) => {
      operation(context, "block");
      context.exploreStatement().forEach(statement);
    },
    enterQueryProperties: (context) => {
      operation(context, "block");
      context.queryStatement().forEach(statement);
    },
    enterSQExtendedSource: (context) => {
      if (!context.INCLUDE()) operation(context, "extend");
    },
    enterSQArrow: (context) => operation(context, "pipe"),
    enterVArrow: (context) => operation(context, "pipe"),
    enterSQID: (context) => {
      if (!context.sourceArguments()) operation(context, "ref", [identifierText(context.id())]);
    },
    enterSegField: (context) => {
      const names = context.fieldPath().fieldName();
      if (names.length === 1) operation(context, "ref", [identifierText(names[0].id())]);
    },
    enterSqlSource: (context) => {
      const string = context.shortString();
      if (string)
        operation(context, "sql", [
          ParseUtil.parseString(string.text, string.text[0]),
          identifierText(context.connectionId().id()),
        ]);
    },
    enterDefDimensions: (context) => {
      if (!context.accessLabel() && !context.tags().annotation().length)
        operation(context, "dimension");
    },
    enterDefMeasures: (context) => {
      if (!context.accessLabel() && !context.tags().annotation().length)
        operation(context, "measure");
    },
    enterDefExploreQuery: (context) => {
      if (!context.accessLabel() && !context.tags().annotation().length) operation(context, "view");
    },
    enterGroupByStatement: (context) => {
      if (
        !context.tags().annotation().length &&
        context.queryFieldList().queryFieldEntry().every(fieldEntry)
      )
        operation(context, "group_by");
    },
    enterAggregateStatement: (context) => {
      if (
        !context.tags().annotation().length &&
        context.queryFieldList().queryFieldEntry().every(fieldEntry)
      )
        operation(context, "aggregate");
    },
    enterProjectStatement: (context) => {
      if (
        !context.tags().annotation().length &&
        context.fieldCollection().collectionMember().every(fieldEntry)
      )
        operation(context, "select");
    },

    enterNestStatement: (context) => {
      nests.push({
        span: context.tags().annotation().length ? undefined : operation(context, "nest"),
        expected: context.nestedQueryList().nestEntry().length,
        named: 0,
      });
    },
    exitNestStatement: () => {
      const nest = nests.pop()!;
      if (nest.span && nest.named !== nest.expected) nest.span.operation = undefined;
    },
    enterOrderByStatement: (context) => {
      const specs = context.ordering().orderBySpec();
      if (specs.some((spec) => !spec.possibleBadPath())) return;
      if (!operation(context, "order_by")) return;
      for (const spec of specs) {
        const reference = spec.possibleBadPath()!;
        const span: Span = {
          kind: "expression",
          name: null,
          start: reference.start.startIndex,
          end: reference.stop!.stopIndex + 1,
          children: [],
        };
        operations.push(span);
        scalars.set(span, { kind: "field", path: reference.badWord().map(identifierText) });
        if (spec.ASC() || spec.DESC()) operation(spec, spec.ASC() ? "asc" : "desc");
      }
    },
    enterLimitStatement: (context) => operation(context, "limit", [context.INTEGER_LITERAL().text]),
    enterDefExplorePrimaryKey: (context) =>
      operation(context, "primary_key", [identifierText(context.fieldName().id())]),
    enterTaggedRef: (context) => {
      if (
        opaque.size ||
        scalarExpressions.has(scopes[scopes.length - 1].expression) ||
        context.tags().annotation().length ||
        context.refExpr()
      )
        return;
      const path = context
        .fieldPath()
        .fieldName()
        .map((name) => identifierText(name.id()));
      const span: Span = {
        kind: "expression",
        name: null,
        start: context.start.startIndex,
        end: context.stop!.stopIndex + 1,
        children: [],
      };
      operations.push(span);
      scalars.set(span, { kind: "field", path });
    },
    enterSourceDefinition: (context) =>
      bind(context, "source", context.sourceNameDef(), context.sqExplore()),
    enterTopLevelQueryDef: (context) =>
      bind(context, "query", context.queryName(), context.sqExpr()),
    enterFieldDef: (context) => bind(context, "field", context.fieldNameDef(), context.fieldExpr()),
    enterExploreQueryDef: (context) =>
      bind(context, "query", context.exploreQueryNameDef(), context.vExpr()),
    enterNestDef: (context) => {
      const name = context.queryName();
      if (name && nests.length) nests[nests.length - 1].named++;
      if (name) bind(context, "query", name, context.vExpr());
      else opaque.add(context);
    },
    enterTopLevelAnonQueryDef: (context: ParserRuleContext) => opaque.add(context),
    enterJoinOn: (context) => {
      const binding = join(context);
      const predicate = context.joinExpression();
      if (binding && predicate) clause(binding, predicate, [predicate.fieldExpr()]);
    },
    enterJoinWith: join,
    enterWhereStatement: (context) => {
      operation(context, "where");
      filter(context);
    },
    enterHavingStatement: (context) => {
      operation(context, "having");
      filter(context);
    },
    enterAnnotation: annotation,
    enterDocAnnotation: annotation,
    exitEveryRule: (context: ParserRuleContext) => {
      opaque.delete(context);
      if (bindings.delete(context)) scopes.pop();
    },
  };
  ParseTreeWalker.DEFAULT.walk(listener, parsed.root);

  const spans: Span[] = [];
  function collect(span: Span): void {
    for (const child of span.children) {
      spans.push(child);
      collect(child);
    }
    span.children = [];
  }
  collect(root);
  const ranges = new Map<string, Span>();
  for (const span of spans) {
    if (span.kind === "expression" || span.kind === "clause")
      ranges.set(`${span.start}:${span.end}`, span);
  }
  for (const span of operations) {
    const key = `${span.start}:${span.end}`;
    const existing = ranges.get(key);
    if (existing) {
      existing.operation ??= span.operation;
      const scalar = scalars.get(span);
      if (scalar) scalars.set(existing, scalar);
    } else {
      ranges.set(key, span);
      spans.push(span);
    }
  }
  for (const table of tableReferences(translator)) {
    const { start, end } = table;
    const span: Span = { kind: "expression", name: null, start, end, children: [] };
    spans.push(span);
    tables.set(span, {
      type: "table",
      source: characters.slice(start, end).join(""),
      connection: table.connection,
      path: table.path,
    });
  }
  // Interval nesting constructs the CST once, avoiding a sibling scan per field.
  spans.sort(
    (left, right) =>
      left.start - right.start ||
      right.end - left.end ||
      Number(tables.has(left)) - Number(tables.has(right)),
  );
  const parents = [root];
  for (const span of spans) {
    while (
      parents.length > 1 &&
      (span.start >= parents[parents.length - 1].end || span.end > parents[parents.length - 1].end)
    )
      parents.pop();
    parents[parents.length - 1].children.push(span);
    parents.push(span);
  }

  function project(span: Span): SyntaxNode {
    const table = tables.get(span);
    if (table) return table;
    const scalar = scalars.get(span);
    if (scalar)
      return { type: "scalar", source: characters.slice(span.start, span.end).join(""), scalar };
    const expression = scalarExpressions.get(span);
    if (expression && !span.children.length) {
      return {
        type: "scalar",
        source: characters.slice(span.start, span.end).join(""),
        scalar: scalarExpression(expression, characters),
      };
    }
    const parts: ConcreteSyntax["parts"] = [];
    let offset = span.start;
    for (const child of span.children.sort((left, right) => left.start - right.start)) {
      if (child.start > offset) parts.push(characters.slice(offset, child.start).join(""));
      parts.push(project(child));
      offset = child.end;
    }
    if (span.end > offset) parts.push(characters.slice(offset, span.end).join(""));
    return {
      type: "syntax",
      kind: span.kind,
      name: span.name,
      parts,
      operation: span.operation ?? null,
    };
  }
  return project(root);
}
