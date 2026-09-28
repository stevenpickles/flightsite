/**
 * The phone Live Map's bottom toolbar (roadmap slice 084, issue #227): one
 * toggle per card the desktop layout floats over the map, each opening its
 * card as a sheet directly above the toolbar.
 *
 * Disclosure buttons (`aria-expanded` + `aria-controls`), not tabs: nothing
 * is selected while every sheet is closed, which is the toolbar's resting
 * state, and a second tap on the open card's button closes it. One card at a
 * time comes from `usePhoneMapStore` having one `openCard` slot.
 *
 * Every button is at least 44 px tall (WCAG 2.5.5's target size), and the
 * whole bar sits above `env(safe-area-inset-bottom)` via its dock's padding
 * so the home indicator on a notched phone never covers a button.
 */

import {
  Activity,
  CalendarDays,
  Filter,
  Layers,
  Star,
  type LucideIcon,
} from "lucide-react";

import { countActiveFilters } from "@/features/filters/lib/activeFilterCount";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import {
  phoneSheetId,
  usePhoneMapStore,
  type PhoneCardId,
} from "@/features/map/phone/usePhoneMapStore";
import { cn } from "@/lib/utils";

interface ToolbarItem {
  id: PhoneCardId;
  label: string;
  icon: LucideIcon;
}

/** Left to right: the summary first, the map's own controls in the middle,
 * the two lists last. */
const PHONE_TOOLBAR_ITEMS: readonly ToolbarItem[] = [
  { id: "today", label: "Today", icon: CalendarDays },
  { id: "layers", label: "Layers", icon: Layers },
  { id: "filters", label: "Filters", icon: Filter },
  { id: "aircraft", label: "Aircraft", icon: Star },
  { id: "activity", label: "Activity", icon: Activity },
];

export function PhoneMapToolbar() {
  const openCard = usePhoneMapStore((state) => state.openCard);
  const toggleCard = usePhoneMapStore((state) => state.toggleCard);
  // The one badge on the bar: without it a phone user would have no sign a
  // filter is narrowing the map short of opening the sheet (the desktop
  // Filters button carries the same count).
  const activeFilters = useFilterStore((state) =>
    countActiveFilters(state.filters),
  );

  return (
    <nav
      aria-label="Map panels"
      data-testid="phone-map-toolbar"
      className="pointer-events-auto flex shrink-0 items-stretch justify-between gap-1 rounded-xl border border-border bg-card/95 p-1 shadow-md backdrop-blur-sm"
    >
      {PHONE_TOOLBAR_ITEMS.map(({ id, label, icon: Icon }) => {
        const open = openCard === id;
        return (
          <button
            key={id}
            type="button"
            aria-expanded={open}
            aria-controls={phoneSheetId(id)}
            onClick={() => toggleCard(id)}
            className={cn(
              "relative flex min-h-11 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-lg px-1 text-[10px] font-medium",
              "outline-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              open
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            <span className="truncate">{label}</span>
            {id === "filters" && activeFilters > 0 && (
              <span
                data-testid="phone-filter-active-count"
                className={cn(
                  "absolute right-1 top-0.5 inline-flex size-4 items-center justify-center rounded-full text-[10px] font-semibold",
                  open
                    ? "bg-accent-foreground text-accent"
                    : "bg-accent text-accent-foreground",
                )}
              >
                {activeFilters}
                <span className="sr-only"> active</span>
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
