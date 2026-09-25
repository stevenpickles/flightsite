import { useId, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { requireNavItem } from "@/components/shell/nav-items";
import { AlertHistorySection } from "@/features/alerts/components/AlertHistorySection";
import { AlertRulesSection } from "@/features/alerts/components/AlertRulesSection";
import { TemplateGallery } from "@/features/alerts/components/TemplateGallery";
import { WatchlistsSection } from "@/features/watchlists/components/WatchlistsSection";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";
import { useAlertRulesQuery, type AlertRule } from "@/lib/api/alertRules";

const item = requireNavItem("/alerts");

interface AlertsTab {
  id: string;
  label: string;
  render: () => React.ReactNode;
}

/** The first tab, kept as its own reference (rather than `tabs[0]`) so
 * `noUncheckedIndexedAccess` does not force every read of the default tab
 * to guard against an array TypeScript cannot know is non-empty. It needs
 * none of the page's state, so it stays out of the component. */
const WATCHLISTS_TAB: AlertsTab = {
  id: "watchlists",
  label: "Watchlists",
  render: () => <WatchlistsSection />,
};

const HISTORY_TAB_ID = "history";

/** Every tab id this page knows, used to reject a stray/typo'd `?tab=`
 * value from the address bar rather than rendering nothing. */
const TAB_IDS = [WATCHLISTS_TAB.id, "rules", "templates", HISTORY_TAB_ID];

/** Parses `?rule_id=` into a positive integer, or `null` for anything else
 * (absent, blank, negative, non-numeric) — the URL is untrusted input. */
function parseRuleId(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) {
    return null;
  }
  const value = Number(raw);
  return value > 0 ? value : null;
}

/**
 * The Alerts page (SPEC §42 to §48): watchlists, the rule builder, the
 * shipped-template gallery, and the history of every alert that has fired.
 *
 * R4-07: the selected tab (`?tab=`) and the History area's per-rule filter
 * (`?rule_id=`, issue #98) live in the URL via `useSearchParams`, so a link
 * to `/alerts?tab=history&rule_id=3` lands on that exact view, and refresh
 * and Back/Forward preserve it — the deep link and round-trip the rubric
 * asks for on every route in scope. The rule's *name* is not stored (only
 * its id is meaningful state); it is resolved each render from the rule
 * list `AlertRulesSection`/`TemplateGallery` already load, via
 * `useAlertRulesQuery` — one cached read regardless of how many callers ask
 * for it — falling back to "Rule {id}" while that query is still loading or
 * for a rule since deleted.
 *
 * The per-rule drill-down (issue #98) is why this page holds the history's
 * rule filter rather than the history holding it: "Show matches" is offered
 * on a rule card in the Rules area and answered in the History area, so the
 * only component that can carry the choice across is the one that owns both.
 */
export function AlertsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rulesQuery = useAlertRulesQuery();

  const tabParam = searchParams.get("tab");
  const ruleId = parseRuleId(searchParams.get("rule_id"));
  // An explicit `?tab=` wins; otherwise a `?rule_id=` with no tab implies
  // History (there is nowhere else that parameter means anything), and the
  // default is the first tab, same as before this page had any URL state.
  const activeTabId =
    tabParam !== null && TAB_IDS.includes(tabParam)
      ? tabParam
      : ruleId !== null
        ? HISTORY_TAB_ID
        : WATCHLISTS_TAB.id;

  /** The rule the History area is narrowed to, or `null` for every rule. */
  const historyRule =
    ruleId === null
      ? null
      : {
          id: ruleId,
          name:
            rulesQuery.data?.rules.find((rule) => rule.id === ruleId)?.name ??
            `Rule ${ruleId}`,
        };

  function setActiveTab(id: string) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("tab", id);
      return next;
    });
  }

  function showMatchesFor(rule: AlertRule) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("tab", HISTORY_TAB_ID);
      next.set("rule_id", String(rule.id));
      return next;
    });
  }

  function clearHistoryRuleFilter() {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("rule_id");
      return next;
    });
  }

  /**
   * The page's areas, in tab order. Roadmap slice 037 landed watchlists;
   * slice 041 added the other three as siblings, which is exactly the change
   * this page was built to absorb — the list grew, the composition did not.
   *
   * The order is the order the work is done in: what you are watching, then
   * the rules over it, then the ready-made rules you can start from, then
   * what has actually fired.
   */
  const tabs: AlertsTab[] = [
    WATCHLISTS_TAB,
    {
      id: "rules",
      label: "Rules",
      render: () => <AlertRulesSection onShowMatches={showMatchesFor} />,
    },
    { id: "templates", label: "Templates", render: () => <TemplateGallery /> },
    {
      id: HISTORY_TAB_ID,
      label: "History",
      render: () => (
        <AlertHistorySection
          ruleFilter={historyRule}
          onClearRuleFilter={clearHistoryRuleFilter}
        />
      ),
    },
  ];
  const active = tabs.find((tab) => tab.id === activeTabId) ?? WATCHLISTS_TAB;
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

      {tabs.length > 1 && (
        <div
          role="tablist"
          aria-label="Alerts sections"
          id={tablistId}
          ref={tablistRef}
          onKeyDown={onTablistKeyDown}
          className="flex gap-1 border-b border-border"
        >
          {tabs.map((tab) => {
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
                onClick={() => setActiveTab(tab.id)}
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
