import type {
  QueryDescriptor,
  Diagnostic,
  DocumentKind,
  Inspection,
  Column,
} from "@malloy-runtime/compiler";
import type { Result } from "@malloydata/malloy-interfaces";
import type { Given } from "./givens";
/** @public */
export type WidgetAction = "inspect" | "check" | "run";
/** @public */
export type ExecutionKind = "browser" | "python" | "result";
/** @title Input */
export interface Input {
  /** @asType integer @minimum 0 */
  revision: number;
  /** @asType integer @minimum 0 */
  definitionRevision: number;
  query: string | null;
  givens: Record<string, Given>;
  action: WidgetAction;
}
/** @title NotebookInfo */
export interface NotebookInfo {
  kind: string;
  source: string;
  execution: ExecutionKind | null;
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
export interface NotebookInspection {
  kind: "inspection";
  inspection: Inspection;
}
export interface NotebookResult {
  kind: "result";
  sql: string;
  columns: Column[];
  connectionName: string;
}
export interface NotebookError {
  kind: "error";
  message: string;
  diagnostics: Diagnostic[];
}
export type NotebookResponse = NotebookInspection | NotebookResult | NotebookError;
export interface ActionRequest {
  /** @asType integer @minimum 0 */
  revision: number;
  action: Exclude<WidgetAction, "inspect">;
}
export interface NotebookRequest {
  kind: "pymalloy-request";
  id: string;
  input: Input;
}
export interface NotebookReply {
  kind: "pymalloy-response";
  id: string;
  response: NotebookResponse;
}
export interface ViewMessage {
  kind: "pymalloy-view";
  id: string;
  action: "mount" | "unmount";
}
export type WidgetMessage = NotebookRequest | ViewMessage;
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
export type DefinitionMetadata = Omit<Definition, "files">;
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
