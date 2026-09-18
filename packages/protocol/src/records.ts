import type { Response } from "./server";
import type {
  CheckReport,
  Inspection,
  Diagnostic,
  QueryDescriptor,
} from "@malloy-runtime/compiler";
import type { State } from "./widget";
export interface Records {
  response: Response;
  check: CheckReport;
  inspection: Inspection;
  diagnostic: Diagnostic;
  query: QueryDescriptor;
  state: State;
}
