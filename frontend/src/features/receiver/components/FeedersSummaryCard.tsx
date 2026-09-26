import { Link } from "react-router-dom";

import { HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import {
  feederStatePresentation,
  worstFeederState,
} from "@/features/feeders/lib/status";
import { useFeedersQuery } from "@/lib/api/feeders";

/**
 * A one-line pointer from the Receiver page to `/receiver/feeders`
 * (roadmap slice 077, design record "Frontend": "`FeedersSummaryCard` on
 * Receiver"). Fetches its own `useFeedersQuery()` rather than threading the
 * payload down from `ReceiverPage`, the same "each card owns its query"
 * shape the rest of this page already uses (`ReceiverScorecard`,
 * `LifetimeStatsSection`).
 *
 * Never hidden for an empty roster: a first-run install with no feeders
 * configured yet is exactly the state this card exists to make discoverable
 * (work package brief) — it names that state and links to Settings instead
 * of disappearing.
 */
export function FeedersSummaryCard() {
  const { data, isError } = useFeedersQuery();

  if (data === undefined) {
    return (
      <HealthCard titleId="receiver-feeders-summary" title="Feeders">
        <p className="text-sm text-muted-foreground">
          {isError ? "Could not load feeders." : "Loading feeders…"}
        </p>
      </HealthCard>
    );
  }

  if (data.feeders.length === 0) {
    return (
      <HealthCard titleId="receiver-feeders-summary" title="Feeders">
        <p className="text-sm text-muted-foreground">
          No feeders configured —{" "}
          <Link
            to="/settings#settings-feeders"
            className="text-accent underline-offset-4 hover:underline"
          >
            add them in Settings
          </Link>
          .
        </p>
      </HealthCard>
    );
  }

  const upCount = data.feeders.filter((feeder) => feeder.state === "up").length;
  const worst = worstFeederState(data.feeders.map((feeder) => feeder.state));
  const presentation = feederStatePresentation(worst);

  return (
    <HealthCard
      titleId="receiver-feeders-summary"
      title="Feeders"
      status={
        <StatusPill tone={presentation.tone} label={presentation.label} />
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">
          {`${upCount} of ${data.feeders.length} feeds up`}
        </p>
        <Link
          to="/receiver/feeders"
          className="text-sm text-accent underline-offset-4 hover:underline"
        >
          View feeders
        </Link>
      </div>
    </HealthCard>
  );
}
