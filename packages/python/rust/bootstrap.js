(() => {
  const core = Deno.core;
  const { URL, URLSearchParams } = core.loadExtScript("ext:deno_web/00_url.js");
  const { TextEncoder, TextDecoder } = core.loadExtScript("ext:deno_web/08_text_encoding.js");
  const { structuredClone } = core.loadExtScript("ext:deno_web/02_structured_clone.js");
  const { performance } = core.loadExtScript("ext:deno_web/15_performance.js");
  Object.assign(globalThis, {
    URL,
    URLSearchParams,
    TextEncoder,
    TextDecoder,
    structuredClone,
    performance,
  });
  globalThis.crypto = Object.freeze({
    getRandomValues(array) {
      if (
        !ArrayBuffer.isView(array) ||
        array instanceof DataView ||
        array instanceof Float32Array ||
        array instanceof Float64Array
      ) {
        throw new TypeError("getRandomValues requires an integer typed array");
      }
      if (array.byteLength > 65536)
        throw new RangeError("getRandomValues is limited to 65536 bytes");
      core.ops.op_pymalloy_random(new Uint8Array(array.buffer, array.byteOffset, array.byteLength));
      return array;
    },
  });
  globalThis.console = Object.freeze({ log() {}, info() {}, warn() {}, error() {}, debug() {} });
})();
