import { useEffect, useRef } from "react";

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
import {
  INITIAL_DECODER_TEST_STATE,
  type DecoderTestState,
  type WizardDraft,
} from "@/features/setup/types";
import { useTestDecoderConnectionMutation } from "@/lib/api/decoder";

export interface DecoderStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
  testState: DecoderTestState;
  onTestStateChange: (state: DecoderTestState) => void;
}

/**
 * Step (c): decoder endpoint (host/port/path), poll interval, and a live
 * connection test (`POST /api/internal/decoder/test`). The decoder may
 * legitimately be offline during setup, so this step never hard-blocks —
 * either a successful test or an explicit, separately-styled "skip" both
 * satisfy `isStepValid`'s check for this step (the parent derives Next's
 * enabled state from `draft` + `testState` there, not from a callback).
 */
export function DecoderStep({
  draft,
  onChange,
  testState,
  onTestStateChange,
}: DecoderStepProps) {
  const hostError = validateHost(draft.receiverHost);
  const portError = validatePort(draft.receiverPort);
  const pathError = validatePath(draft.receiverPath);
  const pollError = validatePollInterval(draft.pollIntervalS);
  const fieldsValid = !hostError && !portError && !pathError && !pollError;

  // Any edit to the tested fields invalidates a previous test outcome —
  // the endpoint being tested is no longer the one the form describes.
  // Skipped intentionally excludes the mount render (see `hasMountedRef`).
  const hasMountedRef = useRef(false);
  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    if (testState.status !== "idle" || testState.skipped) {
      onTestStateChange(INITIAL_DECODER_TEST_STATE);
    }
    // Deliberately reacts only to the tested fields — including
    // `testState`/`onTestStateChange` here would re-fire immediately after
    // the reset this effect itself performs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    draft.receiverHost,
    draft.receiverPort,
    draft.receiverPath,
    draft.pollIntervalS,
  ]);

  const testMutation = useTestDecoderConnectionMutation();

  function handleTest() {
    if (!fieldsValid) {
      return;
    }
    onTestStateChange({ status: "testing", skipped: false, message: null });
    testMutation.mutate(
      {
        host: draft.receiverHost.trim(),
        port: Math.trunc(Number(draft.receiverPort)),
        path: draft.receiverPath.trim(),
        poll_interval_s: Number(draft.pollIntervalS),
      },
      {
        onSuccess: (result) => {
          onTestStateChange({
            status: result.ok ? "success" : "error",
            skipped: false,
            message: result.ok
              ? describeConnectionSuccess(result)
              : describeConnectionFailure(result),
          });
        },
        onError: (error) => {
          onTestStateChange({
            status: "error",
            skipped: false,
            message:
              error instanceof Error
                ? error.message
                : "Connection test failed.",
          });
        },
      },
    );
  }

  function handleSkip() {
    onTestStateChange({ status: "idle", skipped: true, message: null });
  }

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          Decoder endpoint
        </h2>
        <p className="text-sm text-muted-foreground">
          Where FlightSite reads live aircraft data from — the JSON endpoint
          served by readsb or dump1090-fa (SPEC §11).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2 flex flex-col gap-1.5 sm:col-span-1">
          <Label htmlFor="setup-decoder-host">Host</Label>
          <Input
            id="setup-decoder-host"
            value={draft.receiverHost}
            placeholder="127.0.0.1"
            aria-invalid={hostError !== null}
            aria-describedby={
              hostError ? "setup-decoder-host-error" : undefined
            }
            onChange={(event) => {
              onChange({ receiverHost: event.target.value });
            }}
          />
          <FieldError id="setup-decoder-host-error" message={hostError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="setup-decoder-port">Port</Label>
          <Input
            id="setup-decoder-port"
            inputMode="numeric"
            value={draft.receiverPort}
            placeholder="8080"
            aria-invalid={portError !== null}
            aria-describedby={
              portError ? "setup-decoder-port-error" : undefined
            }
            onChange={(event) => {
              onChange({ receiverPort: event.target.value });
            }}
          />
          <FieldError id="setup-decoder-port-error" message={portError} />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5">
          <Label htmlFor="setup-decoder-path">Path</Label>
          <Input
            id="setup-decoder-path"
            value={draft.receiverPath}
            placeholder="/data/aircraft.json"
            aria-invalid={pathError !== null}
            aria-describedby={
              pathError ? "setup-decoder-path-error" : undefined
            }
            onChange={(event) => {
              onChange({ receiverPath: event.target.value });
            }}
          />
          <FieldError id="setup-decoder-path-error" message={pathError} />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5 sm:col-span-1">
          <Label htmlFor="setup-decoder-poll">Poll interval (s)</Label>
          <Input
            id="setup-decoder-poll"
            inputMode="decimal"
            value={draft.pollIntervalS}
            placeholder="1"
            aria-invalid={pollError !== null}
            aria-describedby={
              pollError ? "setup-decoder-poll-error" : undefined
            }
            onChange={(event) => {
              onChange({ pollIntervalS: event.target.value });
            }}
          />
          <FieldError id="setup-decoder-poll-error" message={pollError} />
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="accent"
            onClick={handleTest}
            disabled={!fieldsValid || testState.status === "testing"}
          >
            {testState.status === "testing" ? "Testing…" : "Test connection"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={handleSkip}>
            Skip test — decoder may be offline
          </Button>
        </div>

        <div role="status" aria-live="polite" className="text-sm">
          {testState.status === "success" && (
            <p className="text-accent-foreground">{testState.message}</p>
          )}
          {testState.status === "error" && (
            <p className="text-destructive">{testState.message}</p>
          )}
          {testState.skipped && (
            <p className="text-muted-foreground">
              Test skipped — you can verify the connection later in Settings.
            </p>
          )}
          {testState.status === "idle" && !testState.skipped && (
            <p className="text-muted-foreground">Not tested yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
