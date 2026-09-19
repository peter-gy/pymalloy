import type { DuckDBBundles } from "@malloy-runtime/browser";
import {
  decodeGivens,
  type Input,
  type Definition,
  type State,
  type ActionRequest,
} from "@pymalloy/protocol";
export type { Input, Definition, State, NotebookResponse, NotebookInfo } from "@pymalloy/protocol";
export type { Diagnostic } from "@malloy-runtime/compiler";
/** @title WidgetModel */
export type WidgetModel = {
  _css: string;
  query: string | null;
  _input: Input | null;
  _definition: Definition | null;
  _runtime: DuckDBBundles | null;
  _state: State | null;
  _request: ActionRequest | null;
  _transient: boolean;
};
export function givens(input: Input) {
  return decodeGivens(input.givens);
}
