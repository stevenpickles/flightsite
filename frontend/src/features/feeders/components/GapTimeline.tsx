import type { CSSProperties } from "react";

import { AvailabilityWindowSelector } from "@/features/feeders/components/AvailabilityWindowSelector";
import {
  buildAvailabilitySegments,
  computeAvailability,
  type AvailabilitySegment,
  type AvailabilityWindow,
} from "@/features/feeders/lib/availability";
import { formatDurationCompact } from "@/features/receiver/lib/format";
import { feederStatePresentation } from "@/features/feeders/lib/status";
import type { FeederEpisode } from "@/lib/api/feeders";

interface GapTimelineProps {
  /** The feeder this row belongs to — only its name/label are needed here,
   * but the whole entry is threaded through so a caller (`FeedersPage`)
   * never has to destructure it twice. */
  feederName: string;
  feederLabel: string;
  episodes: readonly FeederEpisode[] | undefined;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  window: AvailabilityWindow;
  onWindowChange: (window: AvailabilityWindow) => void;
  timezone: string;
}

/** Diagonal-stripe/dot patterns per state, layered over the tone color so
 * the bar reads correctly without color (SPEC §80) — a "down" segment is
 * never identified by red alone. `up` stays a plain fill: it is the
 * majority case on a healthy feeder and the one state that needs no extra
 * signal to stand out from the others. */
const SEGMENT_STYLE: Record<
  AvailabilitySegment["state"],
  { className: string; backgroundImage?: string }
> = {
  up: { className: "bg-success-on-surface/80" },
  degraded: {
    className: "bg-warning/70",
    backgroundImage:
      "repeating-linear-gradient(45deg, transparent 0 4px, rgba(255,255,255,0.45) 4px 8px)",
  },
  down: {
    className: "bg-destructive/80",
    backgroundImage:
      "repeating-linear-gradient(-45deg, transparent 0 3px, rgba(255,255,255,0.5) 3px 6px)",
  },
  unknown: {
    className: "bg-muted-foreground/25",
    backgroundImage: "radial-gradient(rgba(0,0,0,0.25) 1px, transparent 1.5px)",
  },
};

function segmentTitle(
  feederLabel: string,
  segment: AvailabilitySegment,
  timezone: string,
): string {
  const label = feederStatePresentation(segment.state).label;
  const startedAt = new Date(segment.startedAt);
  const endedAt = new Date(segment.endedAt);
  const durationS = Math.max(
    0,
    (endedAt.getTime() - startedAt.getTime()) / 1000,
  );
  const range = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return (
    `${feederLabel}: ${label} for ${formatDurationCompact(durationS)} ` +
    `(${range.format(startedAt)}–${range.format(endedAt)})`
  );
}

/**
 * One feeder's episode history as a horizontal bar (design record
 * "Frontend"): `24h`/`7d`/`30d` window selector, an availability
 * percentage derived from the same segments the bar renders
 * (`features/feeders/lib/availability.ts`), and pattern-plus-color segments
 * that stay keyboard-focusable with a full `title` — a screen reader or
 * keyboard user can inspect every episode, not just see a colored strip.
 *
 * Horizontally scrollable at phone width (design record: "the timeline
 * scrolls horizontally with an affordance") rather than compressed to
 * illegibility — the "Scroll for the full range" hint only shows once the
 * bar is actually wider than its container.
 */
export function GapTimeline({
  feederName,
  feederLabel,
  episodes,
  isLoading,
  isError,
  errorMessage,
  window,
  onWindowChange,
  timezone,
}: GapTimelineProps) {
  const segments =
    episodes !== undefined
      ? buildAvailabilitySegments(episodes, window, new Date())
      : [];
  const availability =
    episodes !== undefined ? computeAvailability(segments, window) : null;
  const availabilityPct = availability?.pct ?? null;
  // Say how much of the window was actually watched when that is less than
  // the whole of it, so "100 % available" over a three-minute-old install
  // is read as exactly that.
  const observedNote =
    availability !== null &&
    availability.pct !== null &&
    availability.observedMs < availability.windowMs * 0.99
      ? ` of ${formatDurationCompact(Math.round(availability.observedMs / 1000))} observed`
      : "";

  return (
    // `data-testid="gap-timeline"` per `e2e/tests/12-feeders.spec.ts`'s
    // convention — one per feeder, alongside `data-feeder`.
    <div
      data-testid="gap-timeline"
      data-feeder={feederName}
      className="flex flex-col gap-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium">{feederLabel}</span>
          {availabilityPct !== null && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {`${availabilityPct.toFixed(1)}% available${observedNote}`}
            </span>
          )}
        </div>
        <AvailabilityWindowSelector
          label={`${feederLabel} timeline window`}
          value={window}
          onChange={onWindowChange}
        />
      </div>

      {isLoading && (
        <p className="text-xs text-muted-foreground">Loading history…</p>
      )}
      {isError && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage ?? "Could not load this feeder's history."}
        </p>
      )}

      {!isLoading && !isError && (
        <>
          <p className="text-xs text-muted-foreground sm:hidden">
            Scroll to see the full range →
          </p>
          <div className="overflow-x-auto">
            <div
              role="list"
              aria-label={`${feederLabel} availability, ${window}`}
              className="flex h-6 min-w-[480px] overflow-hidden rounded border border-border"
            >
              {segments.map((segment, index) => {
                const style = SEGMENT_STYLE[segment.state];
                const cssStyle: CSSProperties = {
                  width: `${segment.widthPct}%`,
                  backgroundImage: style.backgroundImage,
                };
                return (
                  <div
                    key={`${feederName}-${segment.startedAt}-${index}`}
                    role="listitem"
                    tabIndex={0}
                    title={segmentTitle(feederLabel, segment, timezone)}
                    className={`h-full shrink-0 ${style.className}`}
                    style={cssStyle}
                  />
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
