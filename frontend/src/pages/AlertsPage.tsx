import { useId, useRef, useState } from "react";

import { requireNavItem } from "@/components/shell/nav-items";
import { AlertHistorySection } from "@/features/alerts/components/AlertHistorySection";
import { AlertRulesSection } from "@/features/alerts/components/AlertRulesSection";
import { TemplateGallery } from "@/features/alerts/components/TemplateGallery";
import { WatchlistsSection } from "@/features/watchlists/components/WatchlistsSection";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";

const item = requireNavItem("/alerts");

interface AlertsTab {
  id: string;
  label: string;
  render: () => React.ReactNode;
}

/** The first tab, kept as its own reference (rather than `TABS[0]`) so
 * `noUncheckedIndexedAccess` does not force every read of the default tab
 * to guard against an array TypeScript cannot know is non-empty. */
const WATCHLISTS_TAB: AlertsTab = {
  id: "watchlists",
  label: "Watchlists",
  render: () => <WatchlistsSection />,
};

/**
 * The Alerts page's areas, in tab order. Roadmap slice 037 landed
 * watchlists; slice 041 adds the other three as siblings, which is exactly
 * the change this page was built to absorb — the list grew, the composition
 * did not.
 *
 * The order is the order the work is done in: what you are watching, then
 * the rules over it, then the ready-made rules you can start from, then
 * what has actually fired.
 */
const TABS: AlertsTab[] = [
  WATCHLISTS_TAB,
  { id: "rules", label: "Rules", render: () => <AlertRulesSection /> },
  { id: "templates", label: "Templates", render: () => <TemplateGallery /> },
  { id: "history", label: "History", render: () => <AlertHistorySection /> },
];

/**
 * The Alerts page (SPEC §42 to §48): watchlists, the rule builder, the
 * shipped-template gallery, and the history of every alert that has fired.
 */
export function AlertsPage() {
  const [activeTabId, setActiveTabId] = useState(WATCHLISTS_TAB.id);
  const active = TABS.find((tab) => tab.id === activeTabId) ?? WATCHLISTS_TAB;
  const tablistId = useId();
  // The tabs use a roving `tabIndex` (one tab stop for the whole tablist), so
  // the arrow keys are the *only* way to reach an unselected tab — without
  // this handler Rules/Templates/History were keyboard-unreachable entirely.
  const tablistRef = useRef<HTMLDivElement>(null);
  const onTablistKeyDown = useRovingFocus(tablistRef, { itemRole: "tab" });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
        <p className="text-sm text-muted-foreground">{item.description}</p>
      </div>

      {TABS.length > 1 && (
        <div
          role="tablist"
          aria-label="Alerts sections"
          id={tablistId}
          ref={tablistRef}
          onKeyDown={onTablistKeyDown}
          className="flex gap-1 border-b border-border"
        >
          {TABS.map((tab) => {
            const selected = tab.id === active.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`alerts-tab-${tab.id}`}
                aria-selected={selected}
                // Only the selected tab's panel is mounted, so only that tab
                // can carry a valid `aria-controls` reference.
                aria-controls={
                  selected ? `alerts-tabpanel-${tab.id}` : undefined
                }
                tabIndex={selected ? 0 : -1}
                onClick={() => setActiveTabId(tab.id)}
                className={
                  selected
                    ? "border-b-2 border-primary px-3 py-2 text-sm font-medium text-foreground"
                    : "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      )}

      <div
        role="tabpanel"
        id={`alerts-tabpanel-${active.id}`}
        aria-labelledby={`alerts-tab-${active.id}`}
      >
        {active.render()}
      </div>
    </div>
  );
}
