import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  describeConnectionFailure,
  describeConnectionSuccess,
} from "@/features/setup/lib/decoderTestMessage";
import {
  validateHost,
  validatePath,
  validatePollInterval,
  validatePort,
} from "@/features/setup/lib/validation";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildDecoderPatch,
  draftFromConfig,
  isSectionDirty,
  pickDecoder,
} from "@/features/settings/lib/draft";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";
import { useTestDecoderConnectionMutation } from "@/lib/api/decoder";

export interface DecoderSectionProps {
  config: FlightSiteConfig;
}

/** Decoder host/port/path/poll interval (SPEC §11), plus the same live
 * connection test the setup wizard offers. Restart required: the ingestion
 * loop reads the receiver endpoint once at process startup. */
export function DecoderSection({ config }: DecoderSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickDecoder(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();
  const testMutation = useTestDecoderConnectionMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);

  const hostError =
    validateHost(draft.receiverHost) ?? fieldErrors["receiver.host"] ?? null;
  const portError =
    validatePort(draft.receiverPort) ?? fieldErrors["receiver.port"] ?? null;
  const pathError =
    validatePath(draft.receiverPath) ?? fieldErrors["receiver.path"] ?? null;
  const pollError =
    validatePollInterval(draft.pollIntervalS) ??
    fieldErrors["receiver.poll_interval_s"] ??
    null;
  const fieldsValid = !hostError && !portError && !pathError && !pollError;

  function updateField(patch: Partial<typeof draft>) {
    setDraft({ ...draft, ...patch });
    testMutation.reset();
  }

  function handleTest() {
    if (!fieldsValid) {
      return;
    }
    testMutation.mutate({
      host: draft.receiverHost.trim(),
      port: Math.trunc(Number(draft.receiverPort)),
      path: draft.receiverPath.trim(),
      poll_interval_s: Number(draft.pollIntervalS),
    });
  }

  function handleSave() {
    mutation.mutate(buildDecoderPatch(draft), {
      onSuccess: (response) => {
        const next = pickDecoder(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  const testResult = testMutation.data;

  return (
    <SettingsSection
      id="settings-decoder"
      title="Decoder"
      description="The readsb / dump1090-fa JSON endpoint FlightSite polls for live aircraft."
      restartRequired
    >
      <div className="grid max-w-lg grid-cols-2 gap-4">
        <div className="col-span-2 flex flex-col gap-1.5 sm:col-span-1">
          <Label htmlFor="settings-decoder-host">Host</Label>
          <Input
            id="settings-decoder-host"
            value={draft.receiverHost}
            aria-invalid={hostError !== null}
            aria-describedby={
              hostError ? "settings-decoder-host-error" : undefined
            }
            onChange={(event) => {
              updateField({ receiverHost: event.target.value });
            }}
          />
          <FieldError id="settings-decoder-host-error" message={hostError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-decoder-port">Port</Label>
          <Input
            id="settings-decoder-port"
            inputMode="numeric"
            value={draft.receiverPort}
            aria-invalid={portError !== null}
            aria-describedby={
              portError ? "settings-decoder-port-error" : undefined
            }
            onChange={(event) => {
              updateField({ receiverPort: event.target.value });
            }}
          />
          <FieldError id="settings-decoder-port-error" message={portError} />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5">
          <Label htmlFor="settings-decoder-path">Path</Label>
          <Input
            id="settings-decoder-path"
            value={draft.receiverPath}
            aria-invalid={pathError !== null}
            aria-describedby={
              pathError ? "settings-decoder-path-error" : undefined
            }
            onChange={(event) => {
              updateField({ receiverPath: event.target.value });
            }}
          />
          <FieldError id="settings-decoder-path-error" message={pathError} />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5 sm:col-span-1">
          <Label htmlFor="settings-decoder-poll">Poll interval (s)</Label>
          <Input
            id="settings-decoder-poll"
            inputMode="decimal"
            value={draft.pollIntervalS}
            aria-invalid={pollError !== null}
            aria-describedby={
              pollError ? "settings-decoder-poll-error" : undefined
            }
            onChange={(event) => {
              updateField({ pollIntervalS: event.target.value });
            }}
          />
          <FieldError id="settings-decoder-poll-error" message={pollError} />
        </div>
      </div>

      <div className="flex max-w-lg flex-col gap-3 rounded-lg border border-border bg-background p-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleTest}
            disabled={!fieldsValid || testMutation.isPending}
          >
            {testMutation.isPending ? "Testing…" : "Test connection"}
          </Button>
        </div>
        <div role="status" aria-live="polite" className="text-sm">
          {testMutation.isPending && (
            <p className="text-muted-foreground">Testing…</p>
          )}
          {testMutation.isSuccess && testResult && (
            <p
              className={
                testResult.ok ? "text-accent-foreground" : "text-destructive"
              }
            >
              {testResult.ok
                ? describeConnectionSuccess(testResult)
                : describeConnectionFailure(testResult)}
            </p>
          )}
          {testMutation.isError && (
            <p className="text-destructive">
              {testMutation.error instanceof Error
                ? testMutation.error.message
                : "Connection test failed."}
            </p>
          )}
        </div>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={!fieldsValid}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
