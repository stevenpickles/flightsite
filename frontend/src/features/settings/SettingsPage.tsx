import { Wand2 } from "lucide-react";
import { Link } from "react-router-dom";

import { requireNavItem } from "@/components/shell/nav-items";
import { AlertsSection } from "@/features/settings/sections/AlertsSection";
import { DecoderSection } from "@/features/settings/sections/DecoderSection";
import { DisplaySection } from "@/features/settings/sections/DisplaySection";
import { EnrichmentSection } from "@/features/settings/sections/EnrichmentSection";
import { MetadataSection } from "@/features/settings/sections/MetadataSection";
import { NotificationsSection } from "@/features/settings/sections/NotificationsSection";
import { ReceiverSection } from "@/features/settings/sections/ReceiverSection";
import { RetentionSection } from "@/features/settings/sections/RetentionSection";
import { UnitsTimeSection } from "@/features/settings/sections/UnitsTimeSection";
import { useConfigQuery } from "@/lib/api/config";

const item = requireNavItem("/settings");
const AERODATABOX_KEY_PATH = "enrichment.aerodatabox_api_key";

/**
 * The Settings page (roadmap slice 019): every configuration section the
 * setup wizard collects, editable afterward, plus the sections the wizard
 * does not manage (display, alert radius, map, retention). Each section
 * saves independently with `PUT /api/internal/config` — see
 * `@/features/settings/lib/draft` for why a per-section patch, and why
 * every editable field here mirrors the wizard's own validation rules.
 */
export function SettingsPage() {
  const configQuery = useConfigQuery();

  if (configQuery.isError) {
    return (
      <div className="flex h-full flex-col items-start justify-center gap-3 px-8">
        <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
        <p className="text-sm text-destructive">
          Could not load the current configuration
          {configQuery.error instanceof Error
            ? `: ${configQuery.error.message}`
            : "."}
        </p>
        <button
          type="button"
          onClick={() => {
            void configQuery.refetch();
          }}
          className="text-sm font-medium text-accent-foreground underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!configQuery.data) {
    return (
      <div className="flex h-full flex-col items-start justify-center gap-2 px-8">
        <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
        <p className="text-sm text-muted-foreground">Loading configuration…</p>
      </div>
    );
  }

  const { config, secrets_set: secretsSet } = configQuery.data;
  const hasStoredKey = secretsSet[AERODATABOX_KEY_PATH] ?? false;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-8">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {item.label}
          </h1>
          <p className="text-sm text-muted-foreground">{item.description}</p>
        </div>
        <Link
          to="/setup"
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-secondary"
        >
          <Wand2 className="size-4" aria-hidden="true" />
          Re-run setup wizard
        </Link>
      </div>

      <div className="flex flex-col gap-4">
        <ReceiverSection config={config} />
        <DecoderSection config={config} />
        <UnitsTimeSection config={config} />
        <DisplaySection config={config} />
        <AlertsSection config={config} />
        <NotificationsSection config={config} />
        <EnrichmentSection config={config} hasStoredKey={hasStoredKey} />
        <MetadataSection timezone={config.timezone} />
        <RetentionSection config={config} />
      </div>
    </div>
  );
}
