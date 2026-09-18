export type DocumentKind = "model" | "notebook";

export const defaultSourceURL = "memory://pymalloy/model.malloy";
export const defaultSourceFilename = "model.malloy";

/** Host convenience for file inputs. Compiler jobs take an explicit document kind. */
export function documentKind(url: URL): DocumentKind {
  return /\.(malloynb|malloysql)$/.test(url.pathname) ? "notebook" : "model";
}
