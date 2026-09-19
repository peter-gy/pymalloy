import type * as BrowserRuntime from "@malloy-runtime/browser";
import type { AnyWidgetBundleApp } from "anywidget-bundle";
import { initialize } from "./initialize";
import { render } from "./view";
import type { WidgetModel } from "./protocol";
import "./host.css";

export default function createWidget() {
  let browser: typeof BrowserRuntime | undefined;
  return {
    initialize: initialize(
      async (options) => {
        browser ??= await import("@malloy-runtime/browser");
        return browser.Session.open(options);
      },
      (error) => (browser && error instanceof browser.ToolingError ? error.diagnostics : []),
    ),
    render,
  } satisfies AnyWidgetBundleApp<WidgetModel>;
}
