import { Malloy, type Model, type DocumentLocation } from "@malloydata/malloy";
import { SchemaConnection, type Column } from "./schema.js";
import { parseURL } from "./upstream.js";
import { documentSource } from "./document.js";
import { diagnostics, ToolingError, toolingError, offsetDiagnostics } from "./diagnostics.js";

export interface LoadOptions {
  url: URL;
  source?: string;
  describe: (sql: string) => Promise<Column[]>;
  readURL: (url: URL) => Promise<string>;
}
type Compile = (
  input: { url: URL } | { source: string; model?: Model; location?: DocumentLocation },
) => Promise<Model>;

export async function loadSource({ url, source: inputSource, describe, readURL }: LoadOptions) {
  const connection = new SchemaConnection(describe);
  const inline = inputSource !== undefined;
  const document = inputSource ?? (await readURL(url));
  const imports = new Map<string, string>();
  const { source, statements } = documentSource(document, url);
  let rootParse: ReturnType<typeof Malloy.parse> | undefined;
  const locations = new Map<string, string>();
  const context = {
    importBaseURL: url,
    urlReader: {
      async readURL(importURL: URL) {
        if (!inline && importURL.href === url.href) return source;
        let imported = imports.get(importURL.href);
        if (imported === undefined) {
          imported = await readURL(importURL);
          imports.set(importURL.href, imported);
        }
        return imported;
      },
    },
  };
  const compile: Compile = async (input) => {
    const lookupErrors = new Map<string, string>();
    const parse = Malloy.parse({
      source: "source" in input ? input.source : source,
      url: "url" in input ? input.url : undefined,
      options: { importBaseURL: url },
    });
    const origin =
      rootParse === undefined
        ? url.href
        : "location" in input && input.location
          ? input.location.url
          : "memory://pymalloy/query.malloy";
    rootParse ??= parse;
    locations.set(parseURL(parse), origin);
    try {
      const result = await Malloy.compile({
        ...context,
        connections: {
          lookupConnection(name?: string) {
            if (name && name !== "duckdb") {
              const message = `Connection '${name}' requires data available through a DuckDB model using 'duckdb'`;
              lookupErrors.set(name, message);
              throw new Error(message);
            }
            return Promise.resolve(connection);
          },
        },
        parse,
        model: "model" in input ? input.model : undefined,
        noThrowOnError: true,
      });
      const problems = result.problems.flatMap((problem) => {
        const contextual =
          lookupErrors.size &&
          problem.code === "failed-to-fetch-table-schema" &&
          problem.message === "import reference failure"
            ? {
                ...problem,
                message: [...lookupErrors.values()].join("\n"),
                data: { connections: [...lookupErrors.keys()] },
              }
            : problem;
        const mapped = diagnostics([contextual], locations);
        return "location" in input && input.location && problem.at?.url === parseURL(parse)
          ? offsetDiagnostics(mapped, input.location, 5)
          : mapped;
      });
      if (problems.some((problem) => problem.severity === "error")) {
        throw new ToolingError(problems.map((problem) => problem.message).join("\n"), problems);
      }
      return result;
    } catch (error) {
      toolingError(error, locations);
    }
  };
  const model = await compile(inline ? { source } : { url });
  for (const statement of statements ?? []) {
    if (statement.type !== "sql") continue;
    for (const embedded of statement.embeddedMalloyQueries) {
      await compile({
        source: `run: ${embedded.query}`,
        model,
        location: { url: url.href, range: embedded.malloyRange },
      });
    }
  }
  return { model, compile, statements, locations, url, document, imports, parse: rootParse! };
}
