/**
 * One-tap common filters, wired to the exact same `useFilterStore` the
 * drawer edits (roadmap slice 017) — a chip is a shortcut into the model,
 * never a second source of truth for it.
 *
 * "Military" targets `classification.military`, which is `null` on every
 * live payload until slice 024 (see `types.ts`'s doc comment): toggling it
 * on today would silently empty the map with no way to tell why, so the
 * chip stays disabled with a tooltip instead of pretending to work.
 * "Emergency" (`emergency` squawk) and "Airborne only" (ground traffic) are
 * real decoder fields today and are fully live.
 */

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
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

  const airborneOnly = filters.groundTraffic === "hide";

  return (
    <TooltipProvider delayDuration={200}>
      <div
        role="group"
        aria-label="Quick filters"
        // Below `ConnectionStatusChip` (left-3 top-3) so the two floating
        // map controls never overlap.
        className="absolute left-3 top-12 z-10 flex flex-wrap gap-1.5"
      >
        <Tooltip>
          <TooltipTrigger asChild>
            {/* A disabled button suppresses its own pointer events in most
             * browsers, so the hover target — and the tooltip trigger — is
             * this wrapping span, not the button itself. */}
            <span data-testid="military-chip-trigger">
              <Chip label="Military" active={false} disabled />
            </span>
          </TooltipTrigger>
          <TooltipContent>Activates with aircraft metadata</TooltipContent>
        </Tooltip>

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
