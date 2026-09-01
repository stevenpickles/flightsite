/**
 * Settings' Danger Zone (SPEC §73, roadmap slice 045): the two destructive,
 * explicitly-confirmed data-reset actions —
 * `POST /api/internal/reset/metadata-cache` and `POST /api/internal/reset/data`
 * (docs/API.md §5). Deliberately not a `SettingsSection` disclosure: this is
 * the one part of the page that must never read as "just another card", so
 * it gets its own always-visible, distinctly styled section at the very
 * bottom of the page, a typed-confirmation dialog per action (nothing here
 * fires from a single click), and a backup suggestion in front of every
 * confirmation (`docs/BACKUP.md`).
 */
import { AlertTriangle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDangerDialog } from "@/features/settings/components/ConfirmDangerDialog";
import {
  CLEAR_METADATA_CONFIRM_PHRASE,
  RESET_DATA_CONFIRM_PHRASE,
  useClearMetadataCacheMutation,
  useResetFlightSiteDataMutation,
} from "@/lib/api/reset";

type OpenDialog = "clear-metadata" | "reset-data" | null;

/** The backup command `docs/BACKUP.md` documents, shown before every
 * confirmation so the suggestion is impossible to miss without reading it. */
const BACKUP_COMMAND =
  "docker compose exec flightsite-backend flightsite-backup create";

function BackupSuggestion() {
  return (
    <p>
      Take a backup first, it only takes a moment and this cannot be undone:
      <br />
      <code className="mt-1 inline-block rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
        {BACKUP_COMMAND}
      </code>{" "}
      (see <code className="font-mono">docs/BACKUP.md</code>).
    </p>
  );
}

export function DangerZoneSection() {
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null);
  const clearMutation = useClearMetadataCacheMutation();
  const resetMutation = useResetFlightSiteDataMutation();

  return (
    <section
      id="settings-danger-zone"
      aria-labelledby="danger-zone-heading"
      className="flex flex-col gap-4 rounded-lg border-2 border-destructive/50 bg-destructive/5 p-4"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle
          className="mt-0.5 size-5 shrink-0 text-destructive"
          aria-hidden="true"
        />
        <div className="space-y-1">
          <h2
            id="danger-zone-heading"
            className="text-base font-semibold tracking-tight text-destructive"
          >
            Danger zone
          </h2>
          <p className="text-sm text-muted-foreground">
            These actions delete data and cannot be undone. Both require you to
            type a confirmation phrase.
          </p>
        </div>
      </div>

      <div className="flex flex-col divide-y divide-destructive/20">
        <div className="flex flex-col gap-2 pb-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-0.5">
            <p className="text-sm font-medium">Clear Metadata Cache</p>
            <p className="text-xs text-muted-foreground">
              Removes imported aircraft metadata, the route cache and airports.
              Aircraft, sighting and analytics history is not affected.
            </p>
          </div>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => setOpenDialog("clear-metadata")}
            className="shrink-0"
          >
            Clear Metadata Cache…
          </Button>
        </div>

        <div className="flex flex-col gap-2 pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-0.5">
            <p className="text-sm font-medium">Reset FlightSite Data</p>
            <p className="text-xs text-muted-foreground">
              Deletes all aircraft, sighting and analytics history. Your
              receiver endpoint and other configuration are kept. Takes effect
              on the next restart.
            </p>
          </div>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => setOpenDialog("reset-data")}
            className="shrink-0"
          >
            Reset FlightSite Data…
          </Button>
        </div>
      </div>

      {clearMutation.isSuccess && (
        <p role="status" className="text-sm text-accent">
          Metadata cache cleared: {clearMutation.data.aircraft_metadata_rows}{" "}
          metadata row(s), {clearMutation.data.route_cache_rows} route-cache
          row(s), {clearMutation.data.airport_rows} airport row(s) removed.
        </p>
      )}
      {clearMutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {clearMutation.error instanceof Error
            ? clearMutation.error.message
            : "Could not clear the metadata cache."}
        </p>
      )}

      {resetMutation.isSuccess && (
        <p role="status" className="text-sm text-accent">
          {resetMutation.data.message}
        </p>
      )}
      {resetMutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {resetMutation.error instanceof Error
            ? resetMutation.error.message
            : "Could not request the reset."}
        </p>
      )}

      <ConfirmDangerDialog
        open={openDialog === "clear-metadata"}
        onClose={() => setOpenDialog(null)}
        title="Clear Metadata Cache"
        confirmPhrase={CLEAR_METADATA_CONFIRM_PHRASE}
        confirmLabel="Clear Metadata Cache"
        pendingLabel="Clearing…"
        isPending={clearMutation.isPending}
        onConfirm={() => {
          clearMutation.mutate(undefined, {
            onSuccess: () => setOpenDialog(null),
          });
        }}
      >
        <p>
          Removes every imported aircraft-metadata row, the route cache and the
          airports table, then rebuilds the in-memory caches from what is left.
          Run "Update Aircraft Metadata" afterward to bring them back. Aircraft,
          sighting and analytics history is not affected.
        </p>
        <BackupSuggestion />
      </ConfirmDangerDialog>

      <ConfirmDangerDialog
        open={openDialog === "reset-data"}
        onClose={() => setOpenDialog(null)}
        title="Reset FlightSite Data"
        confirmPhrase={RESET_DATA_CONFIRM_PHRASE}
        confirmLabel="Reset FlightSite Data"
        pendingLabel="Requesting…"
        isPending={resetMutation.isPending}
        onConfirm={() => {
          resetMutation.mutate(undefined, {
            onSuccess: () => setOpenDialog(null),
          });
        }}
      >
        <p>
          Deletes all aircraft, sighting and analytics history and starts
          FlightSite over as a fresh install. Your receiver endpoint and other
          configuration are kept. This does not happen immediately — it takes
          effect the next time FlightSite restarts.
        </p>
        <BackupSuggestion />
      </ConfirmDangerDialog>
    </section>
  );
}
