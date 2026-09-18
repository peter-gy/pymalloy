import type { QueryDescriptor, Diagnostic, DocumentKind } from "@malloy-runtime/compiler";
import type { Result } from "@malloydata/malloy-interfaces";
import type { Given } from "./givens";
/** @title Input */
export interface Input {
  /** @asType integer @minimum 0 */
  revision: number;
  definitionRevision: number;
  query: string | null;
  givens: Record<string, Given>;
}
/** @title Definition */
export interface Definition {
  /** @asType integer @minimum 0 */
  revision: number;
  source: string;
  documentKind: DocumentKind;
  connectionName: string;
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
}
