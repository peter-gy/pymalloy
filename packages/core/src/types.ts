import type { Result as MalloyResult } from "@malloydata/malloy-interfaces";
import type { GivenValue } from "@malloydata/malloy";
import type { SourceLocation } from "./metadata";
export type Value =
  | null
  | string
  | number
  | bigint
  | boolean
  | Date
  | ArrayBufferView
  | Value[]
  | Row;
/** @title Row */
export interface Row {
  [column: string]: Value;
}
/** @title Column */
export interface Column {
  name: string;
  type: string;
}
/** @title Result */
export interface Result {
  sql: string;
  columns: Column[];
  rows: Row[];
  malloy: MalloyResult;
}
/**
 * A query available on a compiled model.
 *
 * name identifies the selection accepted by Model.query, including zero-based
 * run:N and sql:N names for unnamed document queries.
 *
 * kind distinguishes an authored run, named query, source view or SQL document
 * cell using the values "run", "named", "view" and "sql".
 *
 * location supplies an authored URL and range when available, otherwise null.
 * Python positions use zero-based lines and Unicode code-point character offsets.
 *
 * @title QueryDescriptor
 */
export interface QueryDescriptor {
  name: string;
  kind: "run" | "named" | "view" | "sql";
  location: SourceLocation | null;
}
export type QuerySelection = string | { malloy: string };
/** @title QueryOptions */
export interface QueryOptions extends OperationOptions {
  givens?: Record<string, GivenValue>;
}
/** @title OperationOptions */
export interface OperationOptions {
  signal?: AbortSignal;
}
/** @title DocumentOptions */
export interface DocumentOptions extends QueryOptions {
  queries?: string[];
  all?: boolean;
}
export type { GivenValue } from "@malloydata/malloy";
export type { ModelSource } from "./model";
export type { Diagnostic } from "./diagnostics";
export type {
  SourceLocation,
  SourcePosition,
  SourceRange,
  AnnotationInfo,
  GivenInfo,
  ImportInfo,
} from "./metadata";

export type { DocumentKind } from "./source";
