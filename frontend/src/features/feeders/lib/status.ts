/**
 * Turning a {@link FeederState} into the health area's shared presentation
 * vocabulary (roadmap slice 077) — the same `StatusTone`/label pattern
 * `features/health/lib/status.ts` established, reused rather than
 * duplicated since this page sits right beside Health and Receiver and
 * should read as the same app.
 */
import type { StatusTone } from "@/features/health/components/StatusPill";
import type { FeederObservability, FeederState } from "@/lib/api/feeders";

export interface StatusPresentation {
  tone: StatusTone;
  label: string;
}

const FEEDER_STATE: Record<FeederState, StatusPresentation> = {
  up: { tone: "ok", label: "Up" },
  degraded: { tone: "warn", label: "Degraded" },
  down: { tone: "bad", label: "Down" },
  unknown: { tone: "unknown", label: "Unknown" },
};

export function feederStatePresentation(
  state: FeederState,
): StatusPresentation {
  return FEEDER_STATE[state];
}

/** The worst (most concerning) of a set of feeder states — for
 * `FeedersSummaryCard`'s single roll-up pill. Order matches the tone
 * severity `StatusPill` renders: a problem anywhere outranks an unknown
 * anywhere, which outranks everything being degraded, which outranks a
 * clean "up" across the board. An empty list reads as `"unknown"` — no
 * feeders configured is not the same claim as "every feeder is healthy". */
const SEVERITY: readonly FeederState[] = ["down", "degraded", "unknown", "up"];

export function worstFeederState(states: readonly FeederState[]): FeederState {
  if (states.length === 0) {
    return "unknown";
  }
  for (const candidate of SEVERITY) {
    if (states.includes(candidate)) {
      return candidate;
    }
  }
  return "unknown";
}

/** A feeder's socket-off explanation (design record: "an observability note
 * when `none`: 'Needs the Docker socket — see Settings'") — `null` for any
 * other observability, so the card only ever shows this note when it is
 * actually true. */
export function observabilityNote(
  observability: FeederObservability,
): string | null {
  return observability === "none"
    ? "Needs the Docker socket — see Settings"
    : null;
}
