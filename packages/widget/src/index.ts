import type { AnyWidget } from "@anywidget/types";
import { Session, ToolingError } from "@malloy-runtime/browser";
import { initialize } from "./initialize";
import type { WidgetModel } from "./protocol";
import { render } from "./view";
import "./widget.css";

export default function createWidget() {
  return {
    initialize: initialize((options) => Session.open(options), ToolingError),
    render,
  } satisfies AnyWidget<WidgetModel>;
}
