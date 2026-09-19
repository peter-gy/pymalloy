import type { DuckDBBundles } from "@malloy-runtime/browser";
import { decodeGivens, type Input, type Definition, type State } from "@pymalloy/protocol";
export type { Input, Definition, State, NotebookResponse, NotebookInfo } from "@pymalloy/protocol";
export type { Diagnostic } from "@malloy-runtime/compiler";
/** @title WidgetModel */
export interface WidgetModel {
  query: string | null;
  _input: Input | null;
  _definition: Definition | null;
  _runtime: DuckDBBundles | null;
  _state: State | null;
  _request: { revision: number; action: "check" | "run" } | null;
  _transient: boolean;
}
export function givens(input: Input) {
  return decodeGivens(input.givens);
}
