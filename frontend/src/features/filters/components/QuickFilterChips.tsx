/**
 * One-tap common filters, wired to the exact same `useFilterStore` the
 * drawer edits (roadmap slice 017) — a chip is a shortcut into the model,
 * never a second source of truth for it. "Military" and the drawer's
 * Military checkbox are the same `classifications` entry seen twice.
 *
 * "Military" targets `classification.military`, which only exists on live
 * payloads once this install has imported aircraft metadata. The chip was
 * hard-disabled from slice 017 until slice 066 because no metadata system
 * existed at all; now that one does, the gate is on the *data*, not on
 * history: `useMetadataAvailable` asks whether any source has rows
 * installed, and the chip toggles for real when it does. With no import the
 * chip stays disabled — turning it on would silently empty the map — and
 * says where to fix that. "Emergency" (`emergency` squawk) and "Airborne
 * only" (ground traffic) are decoder fields and are always live.
 */

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { useMetadataAvailable } from "@/lib/api/metadata";
import { cn } from "@/lib/utils";

function Chip({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        active
          ? "border-accent bg-accent text-accent-foreground"
          : "border-border bg-card/95 text-foreground hover:bg-secondary",
      )}
    >
      {label}
    </button>
  );
}

export function QuickFilterChips() {
  const filters = useFilterStore((state) => state.filters);
  const setEmergencyOnly = useFilterStore((state) => state.setEmergencyOnly);
  const setGroundTraffic = useFilterStore((state) => state.setGroundTraffic);
  const toggleClassification = useFilterStore(
    (state) => state.toggleClassification,
  );
  const metadataAvailable = useMetadataAvailable();

  const airborneOnly = filters.groundTraffic === "hide";
  // Read from the store either way, disabled or not: the drawer's checkbox
  // stays interactive without metadata, and a filter restored from the URL
  // can arrive military-selected, so the chip reports the model rather than
  // its own availability.
  const militaryActive = filters.classifications.includes("military");

  return (
    <TooltipProvider delayDuration={200}>
      <div
        role="group"
        aria-label="Quick filters"
        // Below `ConnectionStatusChip` (left-3 top-3) so the two floating
        // map controls never overlap.
        className="absolute left-3 top-12 z-10 flex flex-wrap gap-1.5"
      >
        {metadataAvailable ? (
          <Chip
            label="Military"
            active={militaryActive}
            onClick={() => toggleClassification("military")}
          />
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              {/* A disabled button suppresses its own pointer events in most
               * browsers, so the hover target — and the tooltip trigger — is
               * this wrapping span, not the button itself. */}
              <span data-testid="military-chip-trigger">
                <Chip label="Military" active={militaryActive} disabled />
              </span>
            </TooltipTrigger>
            <TooltipContent>
              No aircraft metadata imported yet — run Settings → Metadata →
              Update Aircraft Metadata
            </TooltipContent>
          </Tooltip>
        )}

        <Chip
          label="Emergency"
          active={filters.emergencyOnly}
          onClick={() => setEmergencyOnly(!filters.emergencyOnly)}
        />

        <Chip
          label="Airborne only"
          active={airborneOnly}
          onClick={() => setGroundTraffic(airborneOnly ? "show" : "hide")}
        />
      </div>
    </TooltipProvider>
  );
}
