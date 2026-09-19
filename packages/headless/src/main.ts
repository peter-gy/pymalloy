import { readSync, writeSync } from "node:fs";
import type { Request, Response } from "@pymalloy/protocol";
import { CompilerService } from "./service";

const limit = 64 * 1024 * 1024;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

function read(length: number): Uint8Array | null {
  const bytes = new Uint8Array(length);
  let offset = 0;
  while (offset < length) {
    const count = readSync(0, bytes, offset, length - offset, null);
    if (count === 0) {
      if (offset === 0) return null;
      throw new Error("Truncated compiler frame");
    }
    offset += count;
  }
  return bytes;
}

function write(bytes: Uint8Array): void {
  let offset = 0;
  while (offset < bytes.length) offset += writeSync(1, bytes, offset, bytes.length - offset);
}

function send(value: Response): void {
  const bytes = encoder.encode(JSON.stringify(value));
  if (bytes.length > limit) throw new Error("Compiler response exceeds 64 MiB");
  const header = new Uint8Array(4);
  new DataView(header.buffer).setUint32(0, bytes.length);
  write(header);
  write(bytes);
}

console.log = console.error;
console.info = console.error;
const compiler = new CompilerService();
send({ kind: "ready" });
while (true) {
  const header = read(4);
  if (!header) break;
  const length = new DataView(header.buffer).getUint32(0);
  if (length === 0 || length > limit) throw new Error("Invalid compiler frame length");
  const bytes = read(length);
  if (!bytes) throw new Error("Missing compiler frame");
  // SAFETY: This private pipe receives Request records from the packaged Python compiler.
  send(compiler.request(JSON.parse(decoder.decode(bytes)) as Request));
}
