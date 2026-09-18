export type File = Uint8Array | { url: string };
export type Files = Readonly<Record<string, File>>;

export const modelURL = new URL("https://pymalloy.local/model.malloy");

export function snapshot(files: Files = {}): Map<string, File> {
  const result = new Map<string, File>();
  for (const [name, file] of Object.entries(files)) {
    const url = new URL(name, modelURL);
    if (url.origin !== modelURL.origin || url.search || url.hash || url.pathname.endsWith("/")) {
      throw new Error(`File name '${name}' must be a virtual file path`);
    }
    if (!name || name.includes("\0")) throw new Error("File names must be nonempty strings");
    if (file instanceof Uint8Array) result.set(name, file.slice());
    else {
      const remote = new URL(file.url);
      if (remote.protocol !== "https:" && remote.protocol !== "http:") {
        throw new Error(`File '${name}' requires an HTTP or HTTPS URL`);
      }
      result.set(name, { url: remote.href });
    }
  }
  return result;
}

export async function readImport(
  files: Map<string, File>,
  url: URL,
  signal: AbortSignal,
  root: URL,
): Promise<string> {
  const names = [...files.keys()].filter((name) => new URL(name, root).href === url.href);
  if (names.length > 1) throw new Error(`Import '${url.pathname}' matches multiple virtual files`);
  const name = names[0];
  const file = name === undefined ? undefined : files.get(name);
  if (!file) throw new Error(`Import '${url.pathname}' is not present in files`);
  if (file instanceof Uint8Array) return new TextDecoder("utf-8", { fatal: true }).decode(file);
  const response = await fetch(file.url, { signal });
  if (!response.ok) throw new Error(`Import '${url.pathname}' returned HTTP ${response.status}`);
  return response.text();
}
