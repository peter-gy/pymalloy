import { tableFromIPC } from "apache-arrow";
import { materialize } from "@malloy-runtime/duckdb/arrow";
import { stableResult } from "@malloy-runtime/duckdb";
import { ToolingError, type Inspection } from "@malloy-runtime/compiler";
import type { Result } from "@malloydata/malloy-interfaces";
import type { AnyModel } from "@anywidget/types";
import type { Input, NotebookResponse, WidgetModel } from "./protocol";

/** Request a bounded native preview over the comm API supported by both hosts. */
function requestNative(
  model: AnyModel<WidgetModel>,
  input: Input,
  signal: AbortSignal,
): Promise<[NotebookResponse, (ArrayBuffer | DataView)[]]> {
  signal.throwIfAborted();
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      model.off("msg:custom", receive);
      signal.removeEventListener("abort", abort);
    };
    const receive = (
      message: { kind?: string; id?: string; response: NotebookResponse } | null,
      buffers: (ArrayBuffer | DataView)[],
    ) => {
      if (message?.kind !== "pymalloy-response" || message.id !== id) return;
      cleanup();
      resolve([message.response, buffers]);
    };
    const abort = () => {
      cleanup();
      reject(signal.reason);
    };
    model.on("msg:custom", receive);
    signal.addEventListener("abort", abort, { once: true });
    try {
      model.send({ kind: "pymalloy-request", id, input });
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}

/** Decode the native transport at the adapter boundary. */
export async function executeNative(
  model: AnyModel<WidgetModel>,
  input: Input,
  signal: AbortSignal,
): Promise<{ inspection: Inspection } | { result: Result }> {
  const [response, buffers] = await requestNative(model, input, signal);
  signal.throwIfAborted();
  if (response.kind === "error") throw new ToolingError(response.message, response.diagnostics);
  if (response.kind === "inspection") return { inspection: response.inspection };
  if (buffers.length !== 1) throw new Error("A native result must contain one Arrow buffer");
  const buffer = buffers[0];
  const bytes = ArrayBuffer.isView(buffer)
    ? new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength)
    : new Uint8Array(buffer);
  const data = materialize(tableFromIPC(bytes));
  return {
    result: stableResult(
      response.sql,
      response.columns,
      data.rows,
      undefined,
      response.connectionName,
    ),
  };
}
