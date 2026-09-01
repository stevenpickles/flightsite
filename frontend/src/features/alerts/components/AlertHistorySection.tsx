import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import {
  builtinKeyLabel,
  SEVERITY_OPTIONS,
} from "@/features/alerts/lib/vocabulary";
import { formatReceiverLocalDateTime } from "@/features/aircraft-detail/lib/format";
import { useAlertMatchesQuery, type AlertMatch } from "@/lib/api/alertMatches";
import { useConfigQuery } from "@/lib/api/config";
import type { AlertSeverity } from "@/lib/api/sightings";

const SELECT_CLASSES =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

const PAGE_SIZE = 25;

/** What produced a match, in one phrase: the rule's name, or the built-in
 * detector's meaning for a match no rule produced (SPEC §47). */
function sourceLabel(match: AlertMatch): string {
  if (match.rule !== null) {
    return match.rule.name ?? `Rule ${match.rule.id}`;
  }
  return match.builtin_key !== null
    ? builtinKeyLabel(match.builtin_key)
    : "Built-in detector";
}

interface MatchRowProps {
  match: AlertMatch;
  timezone: string;
}

function MatchRow({ match, timezone }: MatchRowProps) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md border border-border bg-card px-3 py-2">
      <time
        dateTime={match.at}
        className="font-mono text-xs text-muted-foreground"
      >
        {formatReceiverLocalDateTime(match.at, timezone)}
      </time>
      <AlertSeverityBadge severity={match.severity} />
      <span className="text-sm text-foreground">{match.reason}</span>
      <Link
        to={`/aircraft/${match.icao}`}
        className="font-mono text-xs text-accent hover:underline"
      >
        {match.icao.toUpperCase()}
      </Link>
      <span className="text-xs text-muted-foreground">
        {sourceLabel(match)}
      </span>
      {match.notified && (
        <span className="text-xs text-muted-foreground">Notified</span>
      )}
    </li>
  );
}

/**
 * The alert match history (docs/API.md §3.9, roadmap slice 041): every alert
 * that has actually fired, newest first.
 *
 * A record rather than a re-derivation. Each row shows the `reason` that was
 * stored when the match happened, so renaming or retuning a rule afterwards
 * does not rewrite what the user was told at the time — and a match whose
 * rule has since been deleted is simply gone, because deleting a rule
 * deletes the matches it produced.
 *
 * Paging is "older/newer" rather than numbered: the endpoint deliberately
 * reports no total, the history growing without bound over a multi-year
 * install, so a page count would be a number nobody can compute. A page
 * that comes back short of `PAGE_SIZE` is the end.
 */
export function AlertHistorySection() {
  const [severity, setSeverity] = useState<AlertSeverity | "">("");
  const [offset, setOffset] = useState(0);
  const severityId = useId();

  const configQuery = useConfigQuery();
  const timezone = configQuery.data?.config.timezone ?? "UTC";

  const matchesQuery = useAlertMatchesQuery({
    limit: PAGE_SIZE,
    offset,
    ...(severity === "" ? {} : { severity }),
  });

  const items = matchesQuery.data?.items ?? [];
  const hasOlder = items.length === PAGE_SIZE;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5 sm:max-w-56">
        <Label htmlFor={severityId}>Severity</Label>
        <select
          id={severityId}
          className={SELECT_CLASSES}
          value={severity}
          onChange={(event) => {
            setSeverity(event.target.value as AlertSeverity | "");
            setOffset(0);
          }}
        >
          <option value="">All severities</option>
          {SEVERITY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {matchesQuery.isPending && (
        <p className="text-sm text-muted-foreground">Loading alert history…</p>
      )}

      {matchesQuery.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load the alert history
          {matchesQuery.error instanceof Error
            ? `: ${matchesQuery.error.message}`
            : "."}
        </p>
      )}

      {matchesQuery.data && items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {offset > 0
            ? "No more alerts in this direction."
            : severity === ""
              ? "No alerts have fired yet."
              : "No alerts have fired at this severity."}
        </p>
      )}

      {items.length > 0 && (
        <ul aria-label="Alert history" className="flex flex-col gap-2">
          {items.map((match) => (
            <MatchRow key={match.id} match={match} timezone={timezone} />
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => {
            setOffset((current) => Math.max(0, current - PAGE_SIZE));
          }}
        >
          Newer
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!hasOlder}
          onClick={() => {
            setOffset((current) => current + PAGE_SIZE);
          }}
        >
          Older
        </Button>
      </div>
    </div>
  );
}
