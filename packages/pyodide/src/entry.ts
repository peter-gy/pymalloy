import { open } from "./runtime";

Object.defineProperty(globalThis, "__pymalloy_browser", {
  value: Object.freeze({ open }),
  configurable: true,
});
