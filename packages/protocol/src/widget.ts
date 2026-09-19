import type {
  QueryDescriptor,
  Diagnostic,
  DocumentKind,
  Inspection,
  Column,
} from "@malloy-runtime/compiler";
import type { Result } from "@malloydata/malloy-interfaces";
import type { Given } from "./givens";
/** @title Input */
export interface Input {
  /** @asType integer @minimum 0 */
  revision: number;
  definitionRevision: number;
  query: string | null;
  givens: Record<string, Given>;
  action: "inspect" | "check" | "run";
}
/** @title NotebookInfo */
export interface NotebookInfo {
  kind: string;
  source: string;
  execution: "browser" | "python" | "result" | null;
  message: string | null;
  bindings: NotebookBinding[];
  references: string[];
  annotations: string[];
  inputs: NotebookInput[];
}
/** @title NotebookBinding */
export interface NotebookBinding {
  name: string;
  kind: string;
  source: string;
}
/** @title NotebookInput */
export interface NotebookInput {
  name: string;
  /** @asType integer @minimum 0 */
  rows: number;
}
export type NotebookResponse =
  | { kind: "inspection"; inspection: Inspection }
  | { kind: "result"; sql: string; columns: Column[]; connectionName: string }
  | { kind: "error"; message: string; diagnostics: Diagnostic[] };
/** @title Definition */
export interface Definition {
  /** @asType integer @minimum 0 */
  revision: number;
  source: string;
  documentKind: DocumentKind;
  connectionName: string;
  notebook: NotebookInfo;
  queries: QueryDescriptor[];
  url?: string | null;
  imports?: Readonly<Record<string, string>> | null;
  files: Record<string, ArrayBufferView | { url: string }>;
}
/** @title State */
export interface State {
  /** @asType integer @minimum 0 */
  revision: number;
  status: "idle" | "loading" | "ready" | "error" | "closed";
  queries: QueryDescriptor[];
  result: Result | null;
  error: string | null;
  diagnostics: Diagnostic[];
  inspection: Inspection | null;
}
