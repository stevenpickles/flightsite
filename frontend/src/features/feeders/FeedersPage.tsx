/**
 * The Feeders page (roadmap slice 077, design record
 * `docs/design/077-feeders-page.md`): the status of every network the
 * receiver feeds, the receiver's own uplink summary, links out to each
 * network and its per-feeder stats page, gaps in feeding history, metric
 * charts, and links to the other locally hosted pages (tar1090,
 * graphs1090, SkyAware, the FR24 feeder UI).
 *
 * Reached at `/receiver/feeders` from the Receiver and Health pages, not an
 * eighth sidebar entry — SPEC §10 fixes the sidebar at seven sections, the
 * same precedent `features/health/HealthPage.tsx` follows.
 */
import { Stethoscope } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { FeederCard } from "@/features/feeders/components/FeederCard";
import { FeederHistorySection } from "@/features/feeders/components/FeederHistorySection";
import { LocalPagesCard } from "@/features/feeders/components/LocalPagesCard";
import { ReceiverUplinkTiles } from "@/features/feeders/components/ReceiverUplinkTiles";
import { formatReceiverLocalClock } from "@/features/receiver/lib/format";
import { describeError } from "@/lib/api/client";
import { FEEDERS_POLL_MS, useFeedersQuery } from "@/lib/api/feeders";
import { useReceiverQuery } from "@/lib/api/receiver";

/** The current time, re-read every `intervalMs` — the same lazy-initial-state
 * plus `setInterval` shape `features/health/HealthPage.tsx`'s `useNow` uses,
 * kept out of the render body itself so relative ages ("since", "last data
 * sent") stay live without violating `react-hooks/purity`. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function FeedersPage() {
  const { data, isLoading, isError, error, refetch, isRefetching } =
    useFeedersQuery();
  const { data: receiver } = useReceiverQuery();
  const timezone = receiver?.timezone ?? "UTC";
  const now = useNow(1_000);

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">Feeders</h1>
        <p className="text-sm text-muted-foreground">
          Every network this receiver feeds, and what it is sending them.
        </p>
        {data !== undefined && (
          <p className="mt-1 text-xs text-muted-foreground">
            {`as of ${formatReceiverLocalClock(data.generated_at, timezone)} · refreshes every ${Math.round(FEEDERS_POLL_MS / 1000)} s`}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <Link
          to="/receiver"
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-secondary"
        >
          Receiver
        </Link>
        <Link
          to="/health"
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-secondary"
        >
          <Stethoscope className="size-4" aria-hidden="true" />
          Health
        </Link>
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6 p-4 md:p-6">
        {header}
        <p role="status" className="text-sm text-muted-foreground">
          Loading feeders…
        </p>
      </div>
    );
  }

  // R4-04 (mirrored from the Health page): a full-page error is reserved
  // for "never loaded" — a poll that starts failing after a good load keeps
  // rendering the last payload, with a retry banner below, rather than
  // replacing every card with a red line.
  if (data === undefined) {
    return (
      <div className="flex flex-col gap-6 p-4 md:p-6">
        {header}
        <p className="text-sm text-destructive">
          {`Could not load feeders: ${describeError(error)}`}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      {header}

      {isError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm"
        >
          <p className="text-warning">
            {`Refreshing failed — showing the state from ${formatReceiverLocalClock(data.generated_at, timezone)}. ${describeError(error)}`}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isRefetching}
            onClick={() => {
              void refetch();
            }}
          >
            {isRefetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-base font-medium">Receiver uplink</h2>
        <ReceiverUplinkTiles receiver={data.receiver} />
      </div>

      {data.feeders.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          <p>No feeders are configured yet.</p>
          <Link
            to="/settings#settings-feeders"
            className="mt-2 inline-block text-accent underline-offset-4 hover:underline"
          >
            Add feeders in Settings
          </Link>
        </div>
      ) : (
        <>
          <div>
            <h2 className="mb-2 text-base font-medium">Feeds</h2>
            {/* `data-testid` rather than a role/label query: a feeder's
                name appears again below in its own `GapTimeline` row
                (`FeederHistorySection`), so tests need an unambiguous way
                to scope to this grid specifically — the same targeted-scope
                precedent `NotificationHealthCard`'s
                `data-testid="health-notification-permission"` sets. */}
            <div
              data-testid="feeders-feed-cards"
              className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
            >
              {data.feeders.map((feeder) => (
                <FeederCard
                  key={feeder.name}
                  feeder={feeder}
                  timezone={timezone}
                  nowMs={now}
                />
              ))}
            </div>
          </div>

          <div>
            <h2 className="mb-2 text-base font-medium">Feeding history</h2>
            <div data-testid="feeders-history" className="flex flex-col gap-6">
              {data.feeders.map((feeder) => (
                <FeederHistorySection
                  key={feeder.name}
                  feederName={feeder.name}
                  feederLabel={feeder.label}
                  timezone={timezone}
                />
              ))}
            </div>
          </div>
        </>
      )}

      <LocalPagesCard localPages={data.local_pages} />
    </div>
  );
}
