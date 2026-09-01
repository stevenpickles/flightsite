import { Button } from "@/components/ui/button";
import {
  WINDOW_LABEL,
  WINDOW_OPTIONS,
  type ReceiverWindow,
} from "@/features/receiver/lib/metricConfig";

interface WindowSelectorProps {
  value: ReceiverWindow;
  onChange: (window: ReceiverWindow) => void;
}

/** 24h/7d/30d window selector for the rate/count/range charts — the daily
 * bar charts (unique aircraft, daily totals) are always daily and unaffected
 * by this control (see `metricConfig.ts`'s `alwaysDaily`). */
export function WindowSelector({ value, onChange }: WindowSelectorProps) {
  return (
    <div
      role="group"
      aria-label="Chart time window"
      className="flex items-center gap-1"
    >
      {WINDOW_OPTIONS.map((window) => (
        <Button
          key={window}
          type="button"
          size="sm"
          variant={window === value ? "default" : "outline"}
          aria-pressed={window === value}
          onClick={() => onChange(window)}
        >
          {WINDOW_LABEL[window]}
        </Button>
      ))}
    </div>
  );
}
