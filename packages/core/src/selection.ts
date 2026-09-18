import { ToolingError } from "./diagnostics";
import type { QuerySelection, QueryDescriptor } from "./types";

export function isMalloyText(value: QuerySelection | undefined): value is { malloy: string } {
  return typeof value === "object";
}

export function selectQuery(queries: readonly QueryDescriptor[], name?: string): QueryDescriptor {
  const selected =
    name ??
    queries.findLast((query) => query.kind === "run")?.name ??
    (queries.length === 1 ? queries[0].name : undefined);
  const query = queries.find((query) => query.name === selected);
  if (!query) {
    const available = queries.map((query) => query.name).join(", ") || "the model has no queries";
    throw new ToolingError(
      name === undefined
        ? `Choose a query from: ${available}`
        : `Unknown query '${name}'. Choose from: ${available}`,
    );
  }
  return query;
}
