import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import * as stylex from "@stylexjs/stylex";
import { Icon, type IconKind } from "./icons";
import { colors, tokens } from "./tokens.stylex";

export type TabId = "source" | "schema" | "context" | "result" | "sql" | "issues";
export interface Tab {
  id: TabId;
  label: string;
  icon: IconKind;
}

export function Tabs({
  tabs,
  active,
  onSelect,
  children,
}: {
  tabs: Tab[];
  active: TabId;
  onSelect: (id: TabId) => void;
  children: ReactNode;
}) {
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const rtl = getComputedStyle(event.currentTarget).direction === "rtl";
    let next: number;
    switch (event.key) {
      case "ArrowRight":
        next = index + (rtl ? -1 : 1);
        break;
      case "ArrowLeft":
        next = index + (rtl ? 1 : -1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = tabs.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    next = (next + tabs.length) % tabs.length;
    onSelect(tabs[next].id);
    list.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }
  return (
    <>
      <div ref={list} role="tablist" aria-label="Inspect Malloy" {...stylex.props(styles.list)}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`${id}-${tab.id}`}
            aria-controls={`${id}-panel`}
            aria-selected={active === tab.id}
            tabIndex={active === tab.id ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => navigate(event, index)}
            {...stylex.props(styles.tab, active === tab.id && styles.active)}
          >
            <Icon kind={tab.icon} />
            {tab.label}
          </button>
        ))}
      </div>
      <div
        id={`${id}-panel`}
        role="tabpanel"
        aria-labelledby={`${id}-${active}`}
        tabIndex={0}
        {...stylex.props(styles.panel)}
      >
        {children}
      </div>
    </>
  );
}
const styles = stylex.create({
  list: {
    display: "flex",
    gap: 4,
    paddingInline: 6,
    overflowX: "auto",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: colors.border,
  },
  tab: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    flexShrink: 0,
    fontFamily: "inherit",
    fontSize: 12,
    fontWeight: 550,
    minHeight: { default: 40, [tokens.touch]: 44 },
    paddingInline: 10,
    paddingBlock: 10,
    borderWidth: 0,
    borderBottomWidth: 2,
    borderBottomStyle: "solid",
    borderBottomColor: "transparent",
    backgroundColor: "transparent",
    color: { default: colors.muted, [tokens.hover]: { ":hover": colors.text } },
    cursor: "pointer",
    outlineWidth: 2,
    outlineStyle: "solid",
    outlineColor: { default: "transparent", ":focus-visible": colors.accent },
    outlineOffset: -3,
  },
  active: { color: colors.accent, borderBottomColor: colors.accent },
  panel: {
    padding: 16,
    maxHeight: 480,
    overflow: "auto",
    minWidth: 0,
    outlineOffset: -3,
    outlineWidth: 2,
    outlineStyle: "solid",
    outlineColor: { default: "transparent", ":focus-visible": colors.accent },
  },
});
