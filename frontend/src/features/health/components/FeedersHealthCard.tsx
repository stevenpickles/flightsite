import { Link } from "react-router-dom";

import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import type { DiagnosticsFeeders } from "@/lib/api/diagnostics";

interface FeedersHealthCardProps {
  feeders: DiagnosticsFeeders;
}

const DOCKER_SOCKET_LABEL: Record<DiagnosticsFeeders["docker_socket"], string> =
  {
    available: "Available",
    unset: "Not configured",
    unreachable: "Configured but unreachable",
  };

/**
 * SPEC §67's feeder roll-up (roadmap slice 077, design record "Backend
 * package"): counts by state plus the Docker socket's own read-state, and a
 * link to the full page. `HealthPage` renders this only when
 * `diagnostics.feeders` is present — absent from any backend older than
 * this slice, in which case the card simply does not exist rather than
 * showing a row of invented zeroes (the same convention
 * `EnrichmentHealthCard`/the Live events card already follow).
 */
export function FeedersHealthCard({ feeders }: FeedersHealthCardProps) {
  const anyDown = feeders.down > 0;
  const anyDegradedOrUnknown = feeders.degraded > 0 || feeders.unknown > 0;
  const status = anyDown
    ? { tone: "bad" as const, label: "Problem" }
    : anyDegradedOrUnknown
      ? { tone: "warn" as const, label: "Degraded" }
      : { tone: "ok" as const, label: "Healthy" };

  return (
    <HealthCard
      titleId="health-feeders"
      title="Feeders"
      description="Every network this receiver feeds (SPEC §67)."
      status={<StatusPill tone={status.tone} label={status.label} />}
    >
      <DetailRow label="Configured" value={feeders.configured} />
      <DetailRow label="Up" value={feeders.up} />
      <DetailRow label="Degraded" value={feeders.degraded} />
      <DetailRow label="Down" value={feeders.down} />
      <DetailRow label="Unknown" value={feeders.unknown} />
      <DetailRow
        label="Docker socket"
        value={DOCKER_SOCKET_LABEL[feeders.docker_socket]}
      />
      <Link
        to="/receiver/feeders"
        className="mt-3 inline-block text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        Open the Feeders page
      </Link>
    </HealthCard>
  );
}
