import { Button } from "@/components/ui/button";
import {
  AVAILABILITY_WINDOWS,
  AVAILABILITY_WINDOW_LABEL,
  type AvailabilityWindow,
} from "@/features/feeders/lib/availability";

interface AvailabilityWindowSelectorProps {
  value: AvailabilityWindow;
  onChange: (window: AvailabilityWindow) => void;
  /** Distinguishes each feeder row's own selector for assistive tech —
   * several render on one page. */
  label: string;
}

/** The 24h/7d/30d selector for one `GapTimeline` row — same shape as
 * `features/receiver/components/WindowSelector.tsx`, kept local rather than
 * shared since that one is typed to `ReceiverWindow`, a different (if
 * string-identical) union. */
export function AvailabilityWindowSelector({
  value,
  onChange,
  label,
}: AvailabilityWindowSelectorProps) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-1">
      {AVAILABILITY_WINDOWS.map((window) => (
        <Button
          key={window}
          type="button"
          size="sm"
          variant={window === value ? "default" : "outline"}
          aria-pressed={window === value}
          onClick={() => onChange(window)}
        >
          {AVAILABILITY_WINDOW_LABEL[window]}
        </Button>
      ))}
    </div>
  );
}
