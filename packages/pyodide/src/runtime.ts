import { Session } from "@malloy-runtime/browser";
import { type Model, type Query } from "@malloy-runtime/compiler";
import { compilerVersion, parseSource, syntaxSource } from "@malloy-runtime/compiler/tooling";
import { protect, protectAsync } from "./errors";
import {
  checkOptions,
  connectionOptions,
  givens,
  inspectOptions,
  modelSpec,
  parseOptions,
  selection,
} from "./wire";

export class BrowserQuery {
  constructor(private readonly query: Query) {}

  sql(givensJSON: string, signal?: AbortSignal): Promise<string> {
    return protectAsync(() => this.query.sql({ givens: givens(givensJSON), signal }));
  }

  run(givensJSON: string, signal?: AbortSignal): Promise<string> {
    return protectAsync(async () => {
      const { sql, columns, malloy } = await this.query.run({ givens: givens(givensJSON), signal });
      return JSON.stringify({ sql, columns, malloy });
    });
  }

  preview(limit: number, givensJSON: string, signal?: AbortSignal): Promise<string> {
    return protectAsync(async () => {
      const { sql, columns, malloy } = await this.query.preview(limit, {
        givens: givens(givensJSON),
        signal,
      });
      return JSON.stringify({ sql, columns, malloy });
    });
  }
}

export class BrowserModel {
  readonly compilerVersion = compilerVersion;
  closed = false;

  constructor(private readonly model: Model) {}

  private current(): Model {
    if (this.closed) throw new Error("Model is closed");
    return this.model;
  }

  queries(): string {
    return protect(() => {
      this.current().source();
      return JSON.stringify(this.model.queries);
    });
  }

  source(): string {
    return protect(() => JSON.stringify(this.current().source()));
  }

  inspect(optionsJSON: string, signal?: AbortSignal): Promise<string> {
    return protectAsync(async () => {
      signal?.throwIfAborted();
      const { url, position } = inspectOptions(optionsJSON);
      return JSON.stringify(
        this.current().inspect({
          url: url === undefined ? undefined : new URL(url),
          position,
        }),
      );
    });
  }

  query(selectionJSON: string): BrowserQuery {
    return protect(() => new BrowserQuery(this.current().query(selection(selectionJSON))));
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.model.close();
  }
}

export class BrowserConnection {
  constructor(private readonly session: Session) {}

  get closed(): boolean {
    return this.session.closed;
  }

  private current(): Session {
    if (this.closed) throw new Error("Connection is closed");
    return this.session;
  }

  model(specJSON: string, signal?: AbortSignal): Promise<BrowserModel> {
    return protectAsync(
      async () => new BrowserModel(await this.current().model(modelSpec(specJSON), { signal })),
    );
  }

  check(text: string, optionsJSON: string, signal?: AbortSignal): Promise<string> {
    return protectAsync(async () => {
      return JSON.stringify(
        await this.current().check(text, { ...checkOptions(optionsJSON), signal }),
      );
    });
  }

  parse(text: string, optionsJSON: string): string {
    return protect(() => {
      this.current();
      const { url, documentKind, position } = parseOptions(optionsJSON);
      return JSON.stringify(
        parseSource(text, {
          url: url === undefined ? undefined : new URL(url),
          documentKind,
          position,
        }),
      );
    });
  }

  format(text: string): string {
    return protect(() => this.current().format(text));
  }

  syntax(text: string, url: string): string {
    return protect(() => {
      this.current();
      return JSON.stringify(syntaxSource(text, new URL(url)));
    });
  }

  close(): Promise<void> {
    return protectAsync(() => this.session.close());
  }
}

export function open(optionsJSON: string, signal?: AbortSignal): Promise<BrowserConnection> {
  return protectAsync(async () => {
    const { name, bundles } = connectionOptions(optionsJSON);
    return new BrowserConnection(
      await Session.open({
        connectionName: name,
        bundles,
        signal,
      }),
    );
  });
}
