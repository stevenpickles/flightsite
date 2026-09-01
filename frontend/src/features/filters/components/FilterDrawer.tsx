/**
 * The live filter drawer (roadmap slice 017): a compact, keyboard-accessible
 * side panel covering every filter dimension in the roadmap's scope list.
 * Toggled by a floating button (mirrors `BasemapSwitcher`'s map-instrument
 * positioning), it edits `useFilterStore` directly — every control here is
 * a thin wrapper around one of that store's setters, so the drawer holds no
 * filter state of its own and can never drift from what the map is
 * actually drawing.
 *
 * Fields that target metadata the decoder does not populate until a later
 * slice (aircraft type/operator/operator group, classification, mission —
 * see `types.ts`'s doc comment) stay fully interactive rather than disabled,
 * but carry an inline note explaining why they will not change what's on the
 * map yet. "Interesting only" was one of those until slice 038 started
 * populating `interesting` and slice 039 surfaced it; its note is gone
 * because the filter now genuinely filters.
 */

import { Filter, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { countActiveFilters } from "@/features/filters/lib/activeFilterCount";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import type {
  ClassificationFlag,
  GroundTrafficMode,
} from "@/features/filters/types";
import { useDialogFocus } from "@/lib/a11y/useDialogFocus";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";
import { cn } from "@/lib/utils";

const CLASSIFICATION_OPTIONS: { value: ClassificationFlag; label: string }[] = [
  { value: "military", label: "Military" },
  { value: "government", label: "Government" },
  { value: "law_enforcement", label: "Law enforcement" },
];

const GROUND_OPTIONS: { value: GroundTrafficMode; label: string }[] = [
  { value: "show", label: "Show" },
  { value: "dim", label: "Dim" },
  { value: "hide", label: "Hide" },
];

/** A metadata-gated field's explanation, reused wherever slice 024/038
 * data is what the filter actually needs. */
function PlumbingNote({ children }: { children: ReactNode }) {
  return <p className="text-[11px] text-muted-foreground">{children}</p>;
}

function FilterSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function numberOrNull(value: string): number | null {
  if (value.trim().length === 0) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function FilterDrawer() {
  const [isOpen, setIsOpen] = useState(false);
  const filters = useFilterStore((state) => state.filters);
  const setAltitudeRange = useFilterStore((state) => state.setAltitudeRange);
  const setMaxDistanceNm = useFilterStore((state) => state.setMaxDistanceNm);
  const setCategoryText = useFilterStore((state) => state.setCategoryText);
  const setOperatorText = useFilterStore((state) => state.setOperatorText);
  const setOperatorGroupText = useFilterStore(
    (state) => state.setOperatorGroupText,
  );
  const toggleClassification = useFilterStore(
    (state) => state.toggleClassification,
  );
  const toggleMissionCategory = useFilterStore(
    (state) => state.toggleMissionCategory,
  );
  const setInterestingOnly = useFilterStore(
    (state) => state.setInterestingOnly,
  );
  const setEmergencyOnly = useFilterStore((state) => state.setEmergencyOnly);
  const setHideNonPositioned = useFilterStore(
    (state) => state.setHideNonPositioned,
  );
  const setGroundTraffic = useFilterStore((state) => state.setGroundTraffic);
  const setHideStale = useFilterStore((state) => state.setHideStale);
  const setLiveSetQuery = useFilterStore((state) => state.setLiveSetQuery);
  const clearAll = useFilterStore((state) => state.clearAll);

  const [missionDraft, setMissionDraft] = useState("");
  // Non-modal drawer: focus moves in on open and back to the trigger on
  // close, but Tab is deliberately NOT trapped — the map behind stays
  // interactive by design.
  const panelRef = useDialogFocus<HTMLDivElement>({ open: isOpen });
  const groundGroupRef = useRef<HTMLDivElement>(null);
  const onGroundKeyDown = useRovingFocus(groundGroupRef, {
    itemRole: "radio",
  });
  const headingId = useId();
  const activeCount = countActiveFilters(filters);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      panelRef.current?.focus();
    }
  }, [isOpen, panelRef]);

  function addMissionCategory() {
    const value = missionDraft.trim();
    if (value.length === 0) {
      return;
    }
    toggleMissionCategory(value);
    setMissionDraft("");
  }

  return (
    <>
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={headingId}
        onClick={() => setIsOpen((open) => !open)}
        className={cn(
          // Below `BasemapSwitcher` (right-3 top-3, up to three rows tall)
          // so the two floating map controls never overlap.
          "absolute right-3 top-40 z-10 flex items-center gap-1.5 rounded-lg border border-border bg-card/95 px-2.5 py-1.5 text-xs font-medium shadow-md backdrop-blur-sm",
          "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          activeCount > 0
            ? "text-accent"
            : "text-foreground hover:bg-secondary",
        )}
      >
        <Filter className="size-3.5" aria-hidden="true" />
        Filters
        {activeCount > 0 && (
          <span
            data-testid="filter-active-count"
            className="inline-flex size-4 items-center justify-center rounded-full bg-accent text-[10px] font-semibold text-accent-foreground"
          >
            {activeCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          id={headingId}
          role="dialog"
          aria-label="Live map filters"
          tabIndex={-1}
          data-testid="filter-drawer"
          className={cn(
            "absolute inset-y-0 right-0 z-20 flex w-[320px] max-w-[90vw] flex-col",
            "border-l border-border bg-card text-card-foreground shadow-lg outline-none",
          )}
        >
          <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Filters</h2>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={activeCount === 0}
                onClick={clearAll}
              >
                Clear all
              </Button>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                aria-label="Close filters"
                className="rounded-md p-1.5 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
          </header>

          <div className="overflow-y-auto">
            <FilterSection title="Live set">
              <Label htmlFor="filter-live-query">
                Callsign, registration, or ICAO
              </Label>
              <Input
                id="filter-live-query"
                placeholder="e.g. BAW, N12345, a1b2c3"
                value={filters.liveSetQuery}
                onChange={(event) => setLiveSetQuery(event.target.value)}
              />
              <PlumbingNote>
                Narrows the live set only — not a global search.
              </PlumbingNote>
            </FilterSection>

            <FilterSection title="Altitude (ft)">
              <div className="flex gap-2">
                <Input
                  aria-label="Minimum altitude"
                  inputMode="numeric"
                  placeholder="Min"
                  value={filters.altitudeMinFt ?? ""}
                  onChange={(event) =>
                    setAltitudeRange(
                      numberOrNull(event.target.value),
                      filters.altitudeMaxFt,
                    )
                  }
                />
                <Input
                  aria-label="Maximum altitude"
                  inputMode="numeric"
                  placeholder="Max"
                  value={filters.altitudeMaxFt ?? ""}
                  onChange={(event) =>
                    setAltitudeRange(
                      filters.altitudeMinFt,
                      numberOrNull(event.target.value),
                    )
                  }
                />
              </div>
            </FilterSection>

            <FilterSection title="Distance (nm)">
              <Input
                aria-label="Maximum distance"
                inputMode="numeric"
                placeholder="Display radius default"
                value={filters.maxDistanceNm ?? ""}
                onChange={(event) =>
                  setMaxDistanceNm(numberOrNull(event.target.value))
                }
              />
              <PlumbingNote>
                Overrides the display-radius default either way — larger or
                smaller. Aircraft beyond the cap stay tracked; only the map
                stops drawing them.
              </PlumbingNote>
            </FilterSection>

            <FilterSection title="Category / operator">
              <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="filter-category">Aircraft type</Label>
                  <Input
                    id="filter-category"
                    value={filters.categoryText}
                    onChange={(event) => setCategoryText(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="filter-operator">Operator</Label>
                  <Input
                    id="filter-operator"
                    value={filters.operatorText}
                    onChange={(event) => setOperatorText(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="filter-operator-group">Operator group</Label>
                  <Input
                    id="filter-operator-group"
                    value={filters.operatorGroupText}
                    onChange={(event) =>
                      setOperatorGroupText(event.target.value)
                    }
                  />
                </div>
              </div>
              <PlumbingNote>
                Activates once aircraft metadata populates these fields (roadmap
                slice 024).
              </PlumbingNote>
            </FilterSection>

            <FilterSection title="Classification">
              <div className="flex flex-col gap-1.5">
                {CLASSIFICATION_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={filters.classifications.includes(option.value)}
                      onChange={() => toggleClassification(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
              <PlumbingNote>
                Selects nothing until aircraft metadata (slice 024) arrives —
                FlightSite never guesses a classification it hasn&apos;t
                confirmed.
              </PlumbingNote>
            </FilterSection>

            <FilterSection title="Mission category">
              <div className="flex gap-2">
                <Input
                  aria-label="Add mission category"
                  placeholder="e.g. medevac"
                  value={missionDraft}
                  onChange={(event) => setMissionDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addMissionCategory();
                    }
                  }}
                />
                <Button type="button" size="sm" onClick={addMissionCategory}>
                  Add
                </Button>
              </div>
              {filters.missionCategories.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {filters.missionCategories.map((mission) => (
                    <li key={mission}>
                      <button
                        type="button"
                        onClick={() => toggleMissionCategory(mission)}
                        className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-secondary"
                      >
                        {mission} ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <PlumbingNote>
                Same as classification: selects nothing until slice 024.
              </PlumbingNote>
            </FilterSection>

            <FilterSection title="Status">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={filters.emergencyOnly}
                  onChange={(event) => setEmergencyOnly(event.target.checked)}
                />
                Emergency squawk only
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={filters.interestingOnly}
                  onChange={(event) => setInterestingOnly(event.target.checked)}
                />
                Interesting only
              </label>
            </FilterSection>

            <FilterSection title="Ground traffic">
              <div
                role="radiogroup"
                aria-label="Ground traffic"
                ref={groundGroupRef}
                onKeyDown={onGroundKeyDown}
                className="flex gap-1"
              >
                {GROUND_OPTIONS.map((option) => {
                  const selected = filters.groundTraffic === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      tabIndex={selected ? 0 : -1}
                      onClick={() => setGroundTraffic(option.value)}
                      className={cn(
                        "flex-1 rounded-md px-2 py-1 text-xs outline-none transition-colors",
                        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                        selected
                          ? "bg-accent text-accent-foreground"
                          : "border border-border text-foreground hover:bg-secondary",
                      )}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </FilterSection>

            <FilterSection title="Staleness">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={filters.hideStale}
                  onChange={(event) => setHideStale(event.target.checked)}
                />
                Hide stale aircraft
              </label>
            </FilterSection>

            <FilterSection title="Non-positioned">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={filters.hideNonPositioned}
                  onChange={(event) =>
                    setHideNonPositioned(event.target.checked)
                  }
                />
                Hide non-positioned aircraft
              </label>
            </FilterSection>
          </div>
        </div>
      )}
    </>
  );
}
