import {
  CheckCircle2,
  CircleDashed,
  Loader2,
  type LucideIcon,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatReceiverLocalTime } from "@/features/aircraft-detail/lib/format";
import { useRelativeAge } from "@/features/aircraft-detail/lib/useRelativeAge";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import { overallMetadataAge } from "@/features/settings/lib/metadataAge";
import {
  useMetadataStatusQuery,
  useTriggerMetadataUpdateMutation,
  type MetadataSourceStatus,
  type MetadataSourceStatusEntry,
} from "@/lib/api/metadata";

export interface MetadataSectionProps {
  /** IANA timezone "last updated" times render in — `config.timezone`
   * (docs/API.md §3.2), the same one the aircraft detail panel uses. */
  timezone: string;
}

const SOURCE_LABELS: Record<string, string> = {
  mictronics: "Mictronics",
  faa: "FAA",
};

function sourceLabel(name: string): string {
  return SOURCE_LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

function epochMsToIso(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

const STATUS_META: Record<
  MetadataSourceStatus,
  { label: string; className: string; icon: LucideIcon; spin?: boolean }
> = {
  ok: {
    label: "Up to date",
    className: "text-accent",
    icon: CheckCircle2,
  },
  failed: { label: "Failed", className: "text-destructive", icon: XCircle },
  "never-run": {
    label: "Never run",
    className: "text-muted-foreground",
    icon: CircleDashed,
  },
  running: {
    label: "Running",
    className: "text-accent",
    icon: Loader2,
    spin: true,
  },
};

function StatusBadge({ status }: { status: MetadataSourceStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium ${meta.className}`}
    >
      <Icon
        className={`size-3.5 ${meta.spin ? "animate-spin" : ""}`}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  );
}

interface SourceCardProps {
  source: MetadataSourceStatusEntry;
  timezone: string;
}

function SourceCard({ source, timezone }: SourceCardProps) {
  const lastSuccessIso =
    source.last_success_ms === null
      ? null
      : epochMsToIso(source.last_success_ms);
  const relativeAge = useRelativeAge(lastSuccessIso);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">{sourceLabel(source.name)}</p>
        <StatusBadge status={source.status} />
      </div>

      {lastSuccessIso === null ? (
        <p className="text-xs text-muted-foreground">Never updated.</p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Last updated {formatReceiverLocalTime(lastSuccessIso, timezone)}
          {relativeAge ? ` · ${relativeAge}` : ""}
        </p>
      )}

      {(source.dataset_version !== null || source.row_count !== null) && (
        <p className="text-xs text-muted-foreground">
          {source.dataset_version !== null &&
            `Version ${source.dataset_version}`}
          {source.dataset_version !== null &&
            source.row_count !== null &&
            " · "}
          {source.row_count !== null &&
            `${source.row_count.toLocaleString()} aircraft`}
        </p>
      )}

      {source.status === "failed" && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2">
          <p role="alert" className="text-xs text-destructive">
            {source.last_error ?? "The update failed."}
          </p>
          <p className="text-xs text-muted-foreground">
            Previous {sourceLabel(source.name)} data is unaffected — this source
            only stopped updating, it did not lose what it had.
          </p>
        </div>
      )}
    </div>
  );
}

function MetadataAgeLine({
  sources,
  timezone,
}: {
  sources: MetadataSourceStatusEntry[];
  timezone: string;
}) {
  const ageMs = overallMetadataAge(sources);
  const ageIso = ageMs === null ? null : epochMsToIso(ageMs);
  const relativeAge = useRelativeAge(ageIso);

  return (
    <p className="text-sm text-muted-foreground">
      Metadata last updated:{" "}
      {ageIso === null ? (
        <span className="font-medium text-foreground">never</span>
      ) : (
        <span className="font-medium text-foreground">
          {formatReceiverLocalTime(ageIso, timezone)}
          {relativeAge ? ` (${relativeAge})` : ""}
        </span>
      )}
    </p>
  );
}

/**
 * Aircraft metadata sources (roadmap slice 025): a status card per
 * registered source (Mictronics, FAA), an overall "last updated" line (the
 * age surface slice 042's health page reads), and the "Update Aircraft
 * Metadata" action. The action polls `GET /metadata/status` until every
 * source has settled — see `@/lib/api/metadata` — and each source's card
 * renders its own outcome independently, so one source failing never hides
 * or delays another's success (SPEC §27).
 */
export function MetadataSection({ timezone }: MetadataSectionProps) {
  const statusQuery = useMetadataStatusQuery();
  const triggerMutation = useTriggerMetadataUpdateMutation();

  const sources = statusQuery.data?.sources ?? [];
  const anyRunning = sources.some((source) => source.status === "running");
  const isBusy = anyRunning || triggerMutation.isPending;

  function handleUpdate() {
    triggerMutation.mutate();
  }

  return (
    <SettingsSection
      id="settings-metadata"
      title="Aircraft Metadata"
      description="Registration, type, and operator data merged from Mictronics and the FAA registry."
    >
      <div className="flex flex-col gap-3">
        <MetadataAgeLine sources={sources} timezone={timezone} />

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleUpdate}
            disabled={isBusy}
          >
            {isBusy ? "Updating…" : "Update Aircraft Metadata"}
          </Button>
          {triggerMutation.isSuccess &&
            triggerMutation.data.already_running && (
              <p className="text-xs text-muted-foreground">
                An update was already running — watching it finish.
              </p>
            )}
          {triggerMutation.isError && (
            <p role="alert" className="text-xs text-destructive">
              {triggerMutation.error instanceof Error
                ? triggerMutation.error.message
                : "Could not start the update."}
            </p>
          )}
        </div>

        {statusQuery.isError && (
          <p role="alert" className="text-sm text-destructive">
            Could not load metadata source status.
          </p>
        )}

        {sources.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {sources.map((source) => (
              <SourceCard
                key={source.name}
                source={source}
                timezone={timezone}
              />
            ))}
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
