import type {
  Fulfilled,
  SourcePosition,
  QuerySelection,
  CheckReport,
  ParseReport,
  Inspection,
  ModelSource,
  DocumentCell,
  QueryDescriptor,
  Needs,
  Diagnostic,
  Column,
} from "@malloy-runtime/compiler";
import type { Given } from "./givens.js";
import type { SyntaxNode } from "@malloy-runtime/compiler/tooling";

type SchemaAnswer = { value: Column[] } | { error: string };
export interface HostAnswers {
  urls: Fulfilled["urls"];
  schemas: Record<string, SchemaAnswer>;
}
export type Request =
  | { op: "begin"; url: string; source?: string }
  | { op: "step"; fulfilled: HostAnswers }
  | { op: "query"; selection?: QuerySelection; givens: Record<string, Given> }
  | { op: "document"; queries?: string[]; all?: boolean; givens: Record<string, Given> }
  | { op: "inspect"; position?: SourcePosition & { url?: string } }
  | { op: "source" }
  | { op: "check"; url: string; source: string; syntaxOnly?: boolean; position?: SourcePosition }
  | { op: "format"; source: string }
  | { op: "parse"; source: string; url: string }
  | { op: "syntax"; source: string; url: string };

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
  | ModelReady
  | QueryReady
  | DocumentReady
  | InspectionReady
  | SourceReady
  | CheckReady
  | ParseReady
  | FormatReady
  | SyntaxReady;
export type Output = Exclude<Response, CompilerReady | CompileNeeds | CompileError>;
