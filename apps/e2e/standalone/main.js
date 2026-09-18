const kernelStatus = document.querySelector('[aria-label="Kernel status"]');
const readback = document.querySelector('[aria-label="Python readback"]');
const target = document.querySelector("#widget");
const listeners = new Map();
const pending = {};
let firstResult;
const lifetime = new AbortController();
const pyodide = await globalThis.loadPyodide();
await pyodide.loadPackage("micropip");
const wheel = await (await fetch("/wheel.json")).json();
pyodide.globals.set("wheel_url", new URL(wheel.url, location.href).href);
pyodide.globals.set("asset_root", new URL("/duckdb/", location.href).href);
await pyodide.runPythonAsync(`
import micropip
await micropip.install(wheel_url)
import json
from pymalloy import MalloyWidget, browser
source = '''
##! experimental.givens
 given: region_filter :: string is 'North'
 source: sales is duckdb.table('sales.csv') extend {
   measure: revenue is amount.sum()
   view: by_region is {group_by: region aggregate: revenue order_by: region}
   view: detail is {group_by: region nest: values is {group_by: amount aggregate: subtotal is amount.sum() order_by: amount} order_by: region}
   view: filtered is {where: region = $region_filter aggregate: revenue}
 }
'''
runtime = browser.Runtime(
    mvp=browser.Bundle(
        module=asset_root + "duckdb-mvp.wasm",
        worker=asset_root + "duckdb-browser-mvp.worker.js",
    ),
    eh=browser.Bundle(
        module=asset_root + "duckdb-eh.wasm",
        worker=asset_root + "duckdb-browser-eh.worker.js",
    ),
)
widget = MalloyWidget(source, files={"sales.csv": "region,amount\\nNorth,40\\nNorth,2\\nSouth,30\\n"}, query="sales.by_region", runtime=runtime)
def model_get(name):
    return json.dumps(widget.get_state(key=name)[name], default=lambda value: {"__buffer__": list(value)})
def model_save(value):
    widget.set_state(json.loads(value))
`);
const get = pyodide.globals.get("model_get");
const save = pyodide.globals.get("model_save");
const publish = () => {
  readback.textContent = pyodide.runPython("json.dumps(widget.state, sort_keys=True)");
  document.querySelector('[aria-label="Python values"]').textContent = pyodide.runPython(
    "repr(widget.state['rows'])",
  );
};
const changed = (name) => {
  if (name === "_state" && !firstResult) {
    const state = model.get("_state");
    if (state?.status === "ready") firstResult = structuredClone(state);
  }
  for (const callback of listeners.get(`change:${name}`) ?? []) callback();
  publish();
};
pyodide.globals.set("notify_change", changed);
await pyodide.runPythonAsync(`
def changed(change):
    notify_change(change["name"])
widget.observe(changed)
`);
const model = {
  get(name) {
    return name in pending
      ? pending[name]
      : JSON.parse(get(name), (_key, value) => {
          // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Decode the tagged binary payload at the Python JSON boundary.
          if (value && typeof value === "object" && "__buffer__" in value) {
            return new DataView(Uint8Array.from(value.__buffer__).buffer);
          }
          return value;
        });
  },
  set(name, value) {
    pending[name] = value;
  },
  save_changes() {
    const values = JSON.stringify(pending);
    for (const key of Object.keys(pending)) delete pending[key];
    save(values);
  },
  on(event, callback) {
    const callbacks = listeners.get(event) ?? new Set();
    callbacks.add(callback);
    listeners.set(event, callbacks);
  },
  off(event, callback) {
    listeners.get(event)?.delete(callback);
  },
};
const stylesheet = document.createElement("style");
stylesheet.textContent = model.get("_css");
document.head.appendChild(stylesheet);
const moduleURL = URL.createObjectURL(new Blob([model.get("_esm")], { type: "text/javascript" }));
const { default: createWidget } = await import(/* @vite-ignore */ moduleURL);
const widgetModule = await createWidget();
const initializeCleanup = await widgetModule.initialize?.({ model, signal: lifetime.signal });
const renderCleanup = await widgetModule.render({ model, el: target, signal: lifetime.signal });
for (const button of document.querySelectorAll("button[data-code]")) {
  button.disabled = false;
  button.addEventListener("click", async () => {
    await pyodide.runPythonAsync(button.dataset.code);
    publish();
  });
}
const replay = document.querySelector("#replay");
replay.disabled = false;
replay.addEventListener("click", () => {
  model.set("_state", firstResult);
  changed("_state");
  delete pending._state;
});
const chart = document.querySelector("#chart");
chart.disabled = false;
chart.addEventListener("click", async () => {
  pyodide.globals.set(
    "chart_source",
    "# bar_chart\nrun: duckdb.table('sales.csv') -> {group_by: region aggregate: revenue is amount.sum()}",
  );
  await pyodide.runPythonAsync(
    "widget.query = None; widget.givens = {}; widget.source = chart_source",
  );
});
const scalars = document.querySelector("#scalars");
scalars.disabled = false;
scalars.addEventListener("click", async () => {
  pyodide.globals.set(
    "scalar_source",
    `run: duckdb.sql("""
    SELECT 9007199254740993::BIGINT AS exact_integer,
      {'value': 9007199254740993::BIGINT} AS nested,
      'NaN'::DOUBLE AS nan_value,
      'Infinity'::DOUBLE AS infinity_value,
      from_hex('00ff') AS binary_value
  """) -> {select: *}`,
  );
  await pyodide.runPythonAsync(
    "widget.query = None; widget.givens = {}; widget.source = scalar_source",
  );
});
const remote = document.querySelector("#remote");
remote.disabled = false;
remote.addEventListener("click", async () => {
  pyodide.globals.set("data_url", new URL("/sales.csv", location.href).href);
  await pyodide.runPythonAsync(
    "widget.files = {'sales.csv': {'url': data_url}}; widget.query = 'sales.by_region'",
  );
});
const close = document.querySelector("#close");
close.disabled = false;
close.addEventListener("click", async () => {
  lifetime.abort();
  await renderCleanup();
  await initializeCleanup();
  await pyodide.runPythonAsync("widget.close()");
  target.replaceChildren();
  URL.revokeObjectURL(moduleURL);
  get.destroy();
  save.destroy();
  kernelStatus.textContent = "Analysis closed";
});
kernelStatus.textContent = "Python ready";
publish();
