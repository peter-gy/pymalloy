import { MalloyTranslator, routeOf } from "@malloydata/malloy";
import type { ParserRuleContext } from "antlr4ts";
import { ParseTreeWalker } from "antlr4ts/tree/ParseTreeWalker.js";
import { diagnostics, ToolingError } from "./diagnostics.js";
import { identifierText, scalarExpression, type Scalar } from "./scalar.js";

/** Lossless authored syntax. Strings retain all syntax outside editable bindings. */
export type SyntaxNode = ConcreteSyntax | ScalarSyntax;

export interface ConcreteSyntax {
  type: "syntax";
  kind: "document" | "source" | "query" | "field" | "expression" | "annotation" | "clause";
  name: string | null;
  parts: Array<string | SyntaxNode>;
}

/** A scalar operation tree paired with its original authored spelling. */
export interface ScalarSyntax {
  type: "scalar";
  source: string;
  scalar: Scalar;
}

// This adapter follows the pinned Malloy parser's listener contract. The package
// exports its translator but not generated context types; keep that boundary here.
interface NamedContext extends ParserRuleContext {
  id(): ParserRuleContext;
}
interface SourceContext extends ParserRuleContext {
  sourceNameDef(): NamedContext;
  sqExplore(): ParserRuleContext;
}
interface QueryContext extends ParserRuleContext {
  queryName(): NamedContext;
  sqExpr(): ParserRuleContext;
}
interface FieldContext extends ParserRuleContext {
  fieldNameDef(): NamedContext;
  fieldExpr(): ParserRuleContext;
}
interface ViewContext extends ParserRuleContext {
  exploreQueryNameDef(): NamedContext;
  vExpr(): ParserRuleContext;
}
interface NestContext extends ParserRuleContext {
  queryName(): NamedContext | undefined;
  vExpr(): ParserRuleContext;
}
interface JoinContext extends ParserRuleContext {
  joinFrom(): ParserRuleContext & {
    joinNameDef(): NamedContext;
    isExplore(): (ParserRuleContext & { sqExpr(): ParserRuleContext }) | undefined;
  };
}
interface JoinOnContext extends JoinContext {
  joinExpression(): (ParserRuleContext & { fieldExpr(): ParserRuleContext }) | undefined;
}
interface FilterContext extends ParserRuleContext {
  filterClauseList(): ParserRuleContext & { fieldExpr(): ParserRuleContext[] };
}

interface Span {
  kind: ConcreteSyntax["kind"];
  name: string | null;
  start: number;
  end: number;
  children: Span[];
}

/** Parse plain Malloy without schema discovery and preserve untouched text exactly. */
export function syntaxSource(
  source: string,
  url = new URL("memory://pymalloy/model.malloy"),
): SyntaxNode {
  if (url.pathname.endsWith(".malloynb") || url.pathname.endsWith(".malloysql")) {
    throw new ToolingError("Structured authoring requires a .malloy document", []);
  }
  const translator = new MalloyTranslator(url.href, url.href, {
    urls: { [url.href]: source },
  });
  const parsed = translator.parseStep.step(translator);
  const problems = diagnostics(translator.problems());
  if (!parsed.parse || problems.some((problem) => problem.severity === "error")) {
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
    if (opaque.size || scopes.length === 1) return;
    const { binding, expression } = scopes[scopes.length - 1];
    const start = context.start.startIndex;
    const end = context.stop!.stopIndex + 1;
    if (start < binding.start || end > expression.start) return;
    // Shared statement annotations remain outside the binding's editable scope.
    const token = characters.slice(start, end).join("");
    const route = routeOf({ value: token });
    if (route !== '"') return;
    binding.children.push({
      kind: "annotation",
      name: route,
      start,
      end,
      children: [],
    });
  }

  ParseTreeWalker.DEFAULT.walk(
    {
      enterSourceDefinition: (context: SourceContext) =>
        bind(context, "source", context.sourceNameDef(), context.sqExplore()),
      enterTopLevelQueryDef: (context: QueryContext) =>
        bind(context, "query", context.queryName(), context.sqExpr()),
      enterFieldDef: (context: FieldContext) =>
        bind(context, "field", context.fieldNameDef(), context.fieldExpr()),
      enterExploreQueryDef: (context: ViewContext) =>
        bind(context, "query", context.exploreQueryNameDef(), context.vExpr()),
      enterNestDef: (context: NestContext) => {
        const name = context.queryName();
        if (name) bind(context, "query", name, context.vExpr());
        else opaque.add(context);
      },
      enterTopLevelAnonQueryDef: (context: ParserRuleContext) => opaque.add(context),
      enterJoinOn: (context: JoinOnContext) => {
        const binding = join(context);
        const predicate = context.joinExpression();
        if (binding && predicate) clause(binding, predicate, [predicate.fieldExpr()]);
      },
      enterJoinWith: join,
      enterWhereStatement: filter,
      enterHavingStatement: filter,
      enterAnnotation: annotation,
      exitEveryRule: (context: ParserRuleContext) => {
        opaque.delete(context);
        if (bindings.delete(context)) scopes.pop();
      },
    },
    parsed.parse.root,
  );

  function project(span: Span): SyntaxNode {
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
    return { type: "syntax", kind: span.kind, name: span.name, parts };
  }
  return project(root);
}
