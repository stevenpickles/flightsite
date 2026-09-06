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
 * Why an empty page is empty, in the narrowest terms that are true: an
 * unfiltered history that has never fired reads differently from a rule that
 * has caught nothing, and both read differently from paging past the end.
 */
function emptyMessage({
  offset,
  severity,
  ruleFilter,
}: {
  offset: number;
  severity: AlertSeverity | "";
  ruleFilter: { id: number; name: string } | null;
}): string {
  if (offset > 0) {
    return "No more alerts in this direction.";
  }
  if (ruleFilter !== null) {
    return severity === ""
      ? `“${ruleFilter.name}” has not fired yet.`
      : `“${ruleFilter.name}” has not fired at this severity.`;
  }
  return severity === ""
    ? "No alerts have fired yet."
    : "No alerts have fired at this severity.";
}

export interface AlertHistorySectionProps {
  /**
   * The rule the history is narrowed to, or `null` for every rule (issue
   * #98). The *name* travels with the id because the heading has to say
   * which rule is on screen, and this section never reads the rule list —
   * asking for it purely to resolve one name it was already handed would be
   * a second request for a string the caller has.
   */
  ruleFilter?: { id: number; name: string } | null;
  /** Drops back to every rule. Absent when the caller offers no per-rule
   * drill-down at all, in which case the clear control is not rendered. */
  onClearRuleFilter?: () => void;
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
 *
 * The rule filter (issue #98) is a *prop*, not state of this section: the
 * "Show matches" affordance that sets it lives on a rule card in a sibling
 * area, so the page above both owns the choice. Filtering is server-side —
 * `rule_id` reaches the endpoint and takes part in the query key — rather
 * than a client-side filter of the current page, which would show a
 * near-empty page whenever the rule in question was not the noisy one.
 *
 * The heading that names the filtered rule appears only *while* a filter is
 * on. Unfiltered, the History tab already says what this is and a permanent
 * "all rules" heading would only restate it; a heading that appears when the
 * view is narrowed and disappears when it is not is the state change worth
 * announcing. It also leaves the unfiltered section — the one the visual
 * baselines photograph — pixel-identical.
 */
export function AlertHistorySection({
  ruleFilter = null,
  onClearRuleFilter,
}: AlertHistorySectionProps = {}) {
  const [severity, setSeverity] = useState<AlertSeverity | "">("");
  const [offset, setOffset] = useState(0);
  const severityId = useId();
  const headingId = useId();

  const configQuery = useConfigQuery();
  const timezone = configQuery.data?.config.timezone ?? "UTC";

  const matchesQuery = useAlertMatchesQuery({
    limit: PAGE_SIZE,
    offset,
    ...(severity === "" ? {} : { severity }),
    ...(ruleFilter === null ? {} : { rule_id: ruleFilter.id }),
  });

  const items = matchesQuery.data?.items ?? [];
  const hasOlder = items.length === PAGE_SIZE;

  return (
    <div
      className="flex flex-col gap-4"
      aria-labelledby={ruleFilter === null ? undefined : headingId}
    >
      {ruleFilter !== null && (
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id={headingId} className="text-sm font-semibold text-foreground">
            Alert history: {ruleFilter.name}
          </h2>
          {onClearRuleFilter && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                // Where you stood in one rule's history says nothing about
                // where to stand in every rule's, so the reset is part of
                // clearing rather than something the caller must remember.
                setOffset(0);
                onClearRuleFilter();
              }}
            >
              Show all rules
            </Button>
          )}
        </div>
      )}

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
          {emptyMessage({ offset, severity, ruleFilter })}
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
