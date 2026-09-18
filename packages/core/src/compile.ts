import {
  MalloyTranslator,
  Model,
  Parse,
  sqlKey,
  type ModelDef,
  type DocumentLocation,
  type PreparedQuery,
} from "@malloydata/malloy";
import { documentSource, sqlParts } from "./document";
import { diagnostics, ToolingError, offsetDiagnostics } from "./diagnostics";
import type { Task, SchemaNeed } from "./job";

type ParseUpdate = Parameters<MalloyTranslator["update"]>[0];

/** @title LoadOptions */
export interface LoadOptions {
  url: URL;
  source?: string;
  connection: { name: string; dialect: string };
}
/** @title Translation */
export interface Translation {
  model: Model;
  definition: ModelDef;
  translator: MalloyTranslator;
}

export interface PreparedSQL {
  connection?: string;
  line: number;
  parts: string[];
  queries: PreparedQuery[];
}

export function* loadSource({ url, source: inputSource, connection }: LoadOptions) {
  function* read(url: string): Task<string> {
    const answers = yield { urls: [url], schemas: [] };
    const answer = answers.urls[url];
    if (!answer) throw new Error(`Missing source answer for '${url}'`);
    if ("error" in answer) throw new Error(answer.error);
    return answer.value;
  }
  const document = inputSource ?? (yield* read(url.href));
  const imports = new Map<string, string>();
  const { source, statements } = documentSource(document, url);
  const locations = new Map<string, string>();
  let sequence = 0;
  function* compile(input: {
    source: string;
    base?: Translation;
    location?: DocumentLocation;
  }): Task<Translation> {
    const root = sequence++ === 0;
    const identity =
      root && inputSource === undefined ? url.href : `memory://pymalloy/compile-${sequence}.malloy`;
    const origin = root ? url.href : (input.location?.url ?? "memory://pymalloy/query.malloy");
    locations.set(identity, origin);
    const translator = new MalloyTranslator(identity, url.href, {
      urls: { ...Object.fromEntries(imports), [identity]: input.source },
    });
    const missingConnections = new Set<string>();
    for (;;) {
      const response = translator.translate(input.base?.definition);
      if (response.final) {
        let problems = diagnostics(response.problems ?? [], locations).map((problem) =>
          problem.code === "failed-to-fetch-table-schema" &&
          problem.message === "import reference failure" &&
          missingConnections.size
            ? {
                ...problem,
                message: [...missingConnections]
                  .map(
                    (name) =>
                      `Connection '${name}' is unavailable. This session provides '${connection.name}'.`,
                  )
                  .join("\n"),
                data: { connections: [...missingConnections] },
              }
            : problem,
        );
        if (input.location) problems = offsetDiagnostics(problems, input.location, 5);
        if (!response.modelDef || problems.some((p) => p.severity === "error")) {
          throw new ToolingError(
            problems.map((p) => p.message).join("\n") || "Malloy compilation failed",
            problems,
          );
        }
        return {
          model: new Model(
            response.modelDef,
            response.problems ?? [],
            [...(input.base?.model.fromSources ?? []), ...(response.fromSources ?? [])],
            response.modelWasModified ? undefined : input.base?.model.getExistingQueryModel(),
          ),
          definition: response.modelDef,
          translator,
        };
      }
      const update: ParseUpdate = {};
      const errors: NonNullable<ParseUpdate["errors"]> = {};
      const rejectConnection = (name: string) => {
        missingConnections.add(name);
        return `Connection '${name}' is unavailable. This session provides '${connection.name}'.`;
      };
      for (const [key, request] of Object.entries(response.connectionDialects ?? {})) {
        if (request.connectionName && request.connectionName !== connection.name) {
          (errors.connectionDialects ??= {})[key] = rejectConnection(request.connectionName);
        } else (update.connectionDialects ??= {})[key] = connection.dialect;
      }
      const schemas: SchemaNeed[] = [];
      for (const [key, table] of Object.entries(response.tables ?? {})) {
        if (table.connectionName && table.connectionName !== connection.name)
          (errors.tables ??= {})[key] = rejectConnection(table.connectionName);
        else
          schemas.push({
            key,
            connection: connection.name,
            sql: `SELECT * FROM ${table.tablePath}`,
            tablePath: table.tablePath,
          });
      }
      if (response.compileSQL) {
        const request = response.compileSQL;
        const key = sqlKey(request.connection, request.selectStr);
        if (request.connection && request.connection !== connection.name)
          (errors.compileSQL ??= {})[key] = rejectConnection(request.connection);
        else schemas.push({ key, connection: connection.name, sql: request.selectStr });
      }
      const urls = response.urls ?? [];
      if (urls.length || schemas.length) {
        const fulfilled = yield { urls, schemas };
        for (const target of urls) {
          const answer = fulfilled.urls[target];
          if (!answer) throw new Error(`Missing source answer for '${target}'`);
          if ("error" in answer) (errors.urls ??= {})[target] = answer.error;
          else {
            (update.urls ??= {})[target] = answer.value;
            imports.set(target, answer.value);
          }
        }
        for (const need of schemas) {
          const answer = fulfilled.schemas[need.key];
          if (!answer) throw new Error(`Missing schema answer for '${need.key}'`);
          const category = need.tablePath === undefined ? "compileSQL" : "tables";
          if ("error" in answer) (errors[category] ??= {})[need.key] = answer.error;
          else if (need.tablePath !== undefined)
            (update.tables ??= {})[need.key] = {
              type: "table",
              name: need.key,
              tablePath: need.tablePath,
              connection: connection.name,
              dialect: connection.dialect,
              fields: answer.value,
            };
          else
            (update.compileSQL ??= {})[need.key] = {
              type: "sql_select",
              name: need.key,
              selectStr: need.sql,
              connection: connection.name,
              dialect: connection.dialect,
              fields: answer.value,
            };
        }
      }
      update.errors = errors;
      if (
        !urls.length &&
        !schemas.length &&
        !response.connectionDialects &&
        !Object.keys(errors).length
      )
        throw new Error("Compiler returned neither a result nor data requests");
      translator.update(update);
    }
  }
  const translation = yield* compile({ source });
  const sqlQueries: PreparedSQL[] = [];
  for (const statement of statements ?? []) {
    if (statement.type !== "sql") continue;
    const queries: PreparedQuery[] = [];
    for (const embedded of statement.embeddedMalloyQueries) {
      const validated = yield* compile({
        source: `run: ${embedded.query}`,
        base: translation,
        location: { url: url.href, range: embedded.malloyRange },
      });
      queries.push(validated.model.preparedQuery);
    }
    sqlQueries.push({
      connection: statement.config?.connection,
      line: statement.range.start.line,
      parts: sqlParts(statement),
      queries,
    });
  }
  return {
    ...translation,
    compile,
    statements,
    sqlQueries,
    locations,
    url,
    document,
    imports,
    parse: new Parse(translation.translator),
    connection,
  };
}

export type LoadedSource = ReturnType<typeof loadSource> extends Task<infer T> ? T : never;
