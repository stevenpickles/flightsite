/**
 * The visible openers of the "What was that?" dialog (roadmap slice 090).
 *
 * - `map` — a pill in the Live Map's top-left control group on desktop,
 *   directly under `RecenterButton`, styled like it and like the measure
 *   tool's ruler beside it. Not on phones: there the dock's top edge sits at
 *   that height (`phone/PhoneMapControls`), and a full-height sheet would
 *   cover it.
 * - `sheet` — the phone layout's opener, at the top of the Activity sheet:
 *   "what just flew over?" is an activity question, and the five-button
 *   toolbar stays five buttons.
 * - `header` — the Activity page header's.
 *
 * `W` on the Live Map opens the same dialog (`useKeyboardShortcuts`).
 */
import { Radar } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useOverheadStore } from "@/features/overhead/useOverheadStore";
import { cn } from "@/lib/utils";

export type OverheadButtonPlacement = "map" | "sheet" | "header";

export function OverheadButton({
  placement,
  className,
}: {
  placement: OverheadButtonPlacement;
  className?: string;
}) {
  const openDialog = useOverheadStore((state) => state.openDialog);

  if (placement === "map") {
    return (
      <button
        type="button"
        onClick={openDialog}
        aria-label="What was that? Find what passed closest overhead"
        title="What was that? (W)"
        data-testid="overhead-open"
        className={cn(
          "pointer-events-auto absolute left-3 top-28 z-10 flex items-center gap-1 rounded-full border border-border bg-card/95 px-2 py-1 text-xs text-muted-foreground shadow-sm backdrop-blur-sm outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          className,
        )}
      >
        <Radar className="size-3.5" aria-hidden="true" />
        What was that?
      </button>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={openDialog}
      data-testid="overhead-open"
      className={cn(placement === "sheet" && "w-full bg-card/95", className)}
    >
      <Radar className="size-3.5" aria-hidden="true" />
      What was that?
    </Button>
  );
}
