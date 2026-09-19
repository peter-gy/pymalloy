import { useModel } from "@anywidget/react";
import { useCallback, useSyncExternalStore } from "react";
import type { WidgetModel } from "./protocol";

export function useValue<Key extends keyof WidgetModel>(key: Key): WidgetModel[Key] {
  const model = useModel<WidgetModel>();
  const subscribe = useCallback(
    (update: () => void) => {
      model.on(`change:${key}`, update);
      return () => model.off(`change:${key}`, update);
    },
    [model, key],
  );
  const snapshot = useCallback(() => model.get(key), [model, key]);
  return useSyncExternalStore(subscribe, snapshot);
}
