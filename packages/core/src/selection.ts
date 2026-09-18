import type { QuerySelection } from "./types.js";

export function isMalloyText(value: QuerySelection | undefined): value is { malloy: string } {
  return typeof value === "object";
}
