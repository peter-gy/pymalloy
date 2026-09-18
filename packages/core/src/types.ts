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
/** @title QueryDescriptor */
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
