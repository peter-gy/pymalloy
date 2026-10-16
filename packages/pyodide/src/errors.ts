import { ToolingError } from "@malloy-runtime/compiler";

class BrowserError extends Error {
  readonly pymalloyError: string;

  constructor(error: Error) {
    super(error.message, { cause: error });
    this.name = "PymalloyBrowserError";
    this.pymalloyError = JSON.stringify({
      kind: error instanceof ToolingError ? "tooling" : "runtime",
      message: this.message,
      diagnostics: error instanceof ToolingError ? error.diagnostics : [],
    });
  }
}

export function protect<T>(operation: () => T): T {
  try {
    return operation();
  } catch (error) {
    throw error instanceof BrowserError
      ? error
      : new BrowserError(error instanceof Error ? error : new Error(String(error)));
  }
}

export async function protectAsync<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw error instanceof BrowserError
      ? error
      : new BrowserError(error instanceof Error ? error : new Error(String(error)));
  }
}
