import type {
  SourcePosition,
  QuerySelection,
  CheckReport,
  ParseReport,
  Inspection,
  ModelSource,
  DocumentCell,
  QueryDescriptor,
  Needs,
  LoadOptions,
  DocumentKind,
  Diagnostic,
  Column,
} from "@malloy-runtime/compiler";
import type { Given } from "./givens";
import type { SyntaxNode } from "@malloy-runtime/compiler/tooling";

export interface URLValue {
  kind: "value";
  value: string;
}
export interface SchemaValue {
  kind: "value";
  value: Column[];
}
export interface HostError {
  kind: "error";
  error: string;
}
export type URLAnswer = URLValue | HostError;
export type SchemaAnswer = SchemaValue | HostError;
export interface HostAnswers {
  urls: Record<string, URLAnswer>;
  schemas: Record<string, SchemaAnswer>;
}
export interface BeginRequest {
  op: "begin";
  url: string;
  source?: string;
  documentKind: DocumentKind;
  connection: LoadOptions["connection"];
}
export interface StepRequest {
  op: "step";
  fulfilled: HostAnswers;
}
export interface QueryRequest {
  op: "query";
  selection?: QuerySelection;
  givens: Record<string, Given>;
}
export interface DocumentRequest {
  op: "document";
  queries?: string[];
  all?: boolean;
  givens: Record<string, Given>;
}
export interface InspectionPosition extends SourcePosition {
  url?: string;
}
export interface InspectRequest {
  op: "inspect";
  position?: InspectionPosition;
}
export interface SourceRequest {
  op: "source";
}
export interface CheckRequest {
  op: "check";
  url: string;
  source: string;
  documentKind: DocumentKind;
  connection: LoadOptions["connection"];
  syntaxOnly?: boolean;
  position?: SourcePosition;
}
export interface FormatRequest {
  op: "format";
  source: string;
}
export interface ParseRequest {
  op: "parse";
  source: string;
  url: string;
  documentKind: DocumentKind;
}
export interface SyntaxRequest {
  op: "syntax";
  source: string;
  url: string;
}
export type Request =
  | BeginRequest
  | StepRequest
  | QueryRequest
  | DocumentRequest
  | InspectRequest
  | SourceRequest
  | CheckRequest
  | FormatRequest
  | ParseRequest
  | SyntaxRequest;

export interface CompilerReady {
  kind: "ready";
}
export interface CompileNeeds {
  kind: "needs";
  needs: Needs;
}
export interface CompileError {
  kind: "error";
  message: string;
  diagnostics: Diagnostic[];
}
export interface CompilerFailure {
  kind: "failure";
  message: string;
}
export interface ModelReady {
  kind: "model";
  queries: readonly QueryDescriptor[];
  compilerVersion: string;
  source: ModelSource;
}
export interface QueryReady {
  kind: "query";
  name: string;
  sql: string;
  line?: number;
}
export interface DocumentReady {
  kind: "document";
  cells: DocumentCell[];
}
export interface InspectionReady {
  kind: "inspection";
  inspection: Inspection;
}
export interface SourceReady {
  kind: "source";
  source: ModelSource;
}
export interface CheckReady {
  kind: "check";
  report: CheckReport;
}
export interface ParseReady {
  kind: "parse";
  report: ParseReport;
}
export interface FormatReady {
  kind: "format";
  source: string;
  diagnostics: Diagnostic[];
}
export interface SyntaxReady {
  kind: "syntax";
  syntax: SyntaxNode;
}
export type Response =
  | CompilerReady
  | CompileNeeds
  | CompileError
  | CompilerFailure
  | ModelReady
  | QueryReady
  | DocumentReady
  | InspectionReady
  | SourceReady
  | CheckReady
  | ParseReady
  | FormatReady
  | SyntaxReady;
export type Output = Exclude<
  Response,
  CompilerReady | CompileNeeds | CompileError | CompilerFailure
>;
