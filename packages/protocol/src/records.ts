import type { Request, Response } from "./headless";
import type {
  CheckReport,
  Inspection,
  Diagnostic,
  QueryDescriptor,
} from "@malloy-runtime/compiler";
import type {
  NotebookInfo,
  State,
  Input,
  NotebookReply,
  WidgetMessage,
  ActionRequest,
  DefinitionMetadata,
} from "./widget";
export interface Records {
  request: Request;
  response: Response;
  input: Input;
  notebookReply: NotebookReply;
  widgetMessage: WidgetMessage;
  actionRequest: ActionRequest;
  definition: DefinitionMetadata;
  check: CheckReport;
  inspection: Inspection;
  diagnostic: Diagnostic;
  query: QueryDescriptor;
  state: State;
  notebook: NotebookInfo;
}
