import type { Response } from "./server.js";
import type {
  CheckReport,
  Inspection,
  Diagnostic,
  QueryDescriptor,
} from "@malloy-runtime/compiler";
import type { State } from "./widget.js";
export interface Records {
  response: Response;
  check: CheckReport;
  inspection: Inspection;
  diagnostic: Diagnostic;
  query: QueryDescriptor;
  state: State;
}
