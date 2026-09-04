/**
 * Turning diagnostics values into the health area's presentation vocabulary
 * (roadmap slice 042).
 *
 * Kept out of the components so that "what counts as degraded" is a pure
 * function with its own tests, rather than a condition buried in JSX. The
 * backend already rolls up an overall status; these helpers cover the
 * per-item states it does not, and the client-only facts (notification
 * permission) it cannot know at all.
 */
import type { StatusTone } from "@/features/health/components/StatusPill";
import type { NotificationPermissionState } from "@/features/notifications/lib/permission";
import type {
  DecoderState,
  DiagnosticsEnrichmentBudget,
  DiagnosticsStatus,
  MetadataSourceState,
} from "@/lib/api/diagnostics";

export interface StatusPresentation {
  tone: StatusTone;
  label: string;
}

const OVERALL: Record<DiagnosticsStatus, StatusPresentation> = {
  ok: { tone: "ok", label: "Healthy" },
  degraded: { tone: "warn", label: "Degraded" },
  down: { tone: "bad", label: "Problem" },
};

export function overallPresentation(
  status: DiagnosticsStatus,
): StatusPresentation {
  return OVERALL[status];
}

const DECODER: Record<DecoderState, StatusPresentation> = {
  connected: { tone: "ok", label: "Connected" },
  degraded: { tone: "warn", label: "Unstable" },
  down: { tone: "bad", label: "Disconnected" },
  // Not a fault: nothing has been configured to be disconnected from yet.
  unconfigured: { tone: "idle", label: "Not configured" },
};

export function decoderPresentation(state: DecoderState): StatusPresentation {
  return DECODER[state];
}

const METADATA_SOURCE: Record<MetadataSourceState, StatusPresentation> = {
  ok: { tone: "ok", label: "Imported" },
  failed: { tone: "warn", label: "Failed" },
  never_run: { tone: "idle", label: "Never imported" },
};

export function metadataSourcePresentation(
  state: MetadataSourceState,
  running: boolean,
): StatusPresentation {
  if (running) {
    return { tone: "unknown", label: "Importing…" };
  }
  return METADATA_SOURCE[state];
}

/**
 * Database integrity, where `null` means no check has run yet.
 *
 * A brand-new install has never had an integrity check, and calling that
 * "healthy" would claim something nobody has verified.
 */
export function integrityPresentation(
  healthy: boolean | null,
): StatusPresentation {
  if (healthy === null) {
    return { tone: "unknown", label: "Not yet checked" };
  }
  return healthy
    ? { tone: "ok", label: "Passed" }
    : { tone: "bad", label: "Failed" };
}

/**
 * Browser notification permission — a fact only the client can observe
 * (`docs/SECURITY.md` §5, which requires denied/blocked to degrade cleanly
 * and be surfaced in diagnostics).
 */
export function notificationPresentation(
  permission: NotificationPermissionState,
  configuredEnabled: boolean,
): StatusPresentation {
  switch (permission) {
    case "granted":
      return configuredEnabled
        ? { tone: "ok", label: "Granted" }
        : { tone: "idle", label: "Granted, alerts off" };
    case "denied":
      return { tone: "warn", label: "Blocked by browser" };
    case "default":
      return { tone: "idle", label: "Not requested" };
    case "insecure-context":
      return { tone: "warn", label: "Needs HTTPS or localhost" };
    case "unsupported":
      return { tone: "idle", label: "Not supported" };
  }
}

/** Maintenance: `null` before the first cycle has run. */
export function maintenancePresentation(
  healthy: boolean | null,
  cycles: number,
): StatusPresentation {
  if (healthy === null || cycles === 0) {
    return { tone: "unknown", label: "Not yet run" };
  }
  // Deliberately not "Healthy": that word belongs to the page's overall
  // status, and two pills reading the same on one screen invites the user to
  // mistake a maintenance result for the whole install's.
  return healthy
    ? { tone: "ok", label: "Running cleanly" }
    : { tone: "warn", label: "A job failed" };
}

/** Why the guarded `VACUUM` last declined, as something an operator can read.
 *
 * Three of the four reasons are the policy working and are reported calmly.
 * `insufficient_free_space` is the one worth a warning: `VACUUM` builds a
 * complete second copy, so its requirement scales with the database and on a
 * large history can exceed anything the card will ever have free — the space
 * is then never reclaimed, and nothing about the wording should suggest it
 * clears itself overnight. */
export function vacuumRefusalPresentation(reason: string): StatusPresentation {
  switch (reason) {
    case "insufficient_free_space":
      return { tone: "warn", label: "Blocked — not enough free space" };
    case "below_size_floor":
      return { tone: "ok", label: "Not needed — database is small" };
    case "little_reclaimable":
      return { tone: "ok", label: "Not needed — little to reclaim" };
    case "ingestion_pressure":
      return { tone: "idle", label: "Deferred — receiver was busy" };
    default:
      // A reason this build does not know about is still worth showing: the
      // backend is the authority on the vocabulary, and hiding an unrecognized
      // one would turn a new refusal into the silence this row exists to end.
      return { tone: "idle", label: humanizeReason(reason) };
  }
}

function humanizeReason(reason: string): string {
  const spaced = reason.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Unclean-shutdown recovery: anomalies are worth surfacing, a clean
 * recovery is not a problem to report. */
export function recoveryPresentation(anomalies: number): StatusPresentation {
  return anomalies > 0
    ? {
        tone: "warn",
        label: `${anomalies} anomal${anomalies === 1 ? "y" : "ies"}`,
      }
    : { tone: "ok", label: "Clean" };
}

/** A recent-error list: any captured error is worth a warning tone. */
export function errorCountPresentation(count: number): StatusPresentation {
  return count > 0
    ? { tone: "warn", label: `${count} recent` }
    : { tone: "ok", label: "None" };
}

/**
 * The enrichment daily budget (slice 070).
 *
 * A spent budget is a `warn`, never a `bad`: enrichment is optional, the
 * cap is one the operator chose, and reaching it means the economy worked —
 * lookups stop, cached and locally-learned routes keep being served, and the
 * counter rolls over at midnight UTC. Calling that an error would train
 * people to ignore the one tone this page reserves for real breakage.
 *
 * `undefined` (a backend older than this slice) yields `null` so the card
 * shows no pill at all rather than an invented state.
 */
export function enrichmentBudgetPresentation(
  budget: DiagnosticsEnrichmentBudget | undefined,
): StatusPresentation | null {
  if (budget === undefined) {
    return null;
  }
  if (budget.limit === null) {
    return { tone: "idle", label: "Uncapped" };
  }
  if ((budget.remaining ?? 0) <= 0) {
    return { tone: "warn", label: "Budget spent" };
  }
  return { tone: "ok", label: `${budget.remaining ?? 0} left today` };
}
