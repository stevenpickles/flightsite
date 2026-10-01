import { useState, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildSelfAlertsPatch,
  draftFromConfig,
  isSectionDirty,
  pickSelfAlerts,
} from "@/features/settings/lib/draft";
import {
  fieldErrorsFrom,
  fieldMessage,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import {
  validateSelfAlertDecoderMinutes,
  validateSelfAlertRateMinutes,
  validateSelfAlertSharePct,
} from "@/features/settings/lib/validation";
import type { SelfAlertsDraft } from "@/features/settings/types";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface SelfAlertsSectionProps {
  config: FlightSiteConfig;
}

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: string;
  description: string;
  children?: ReactNode;
}

/** One condition: its switch, what it means, and its thresholds beneath. */
function ConditionToggle({
  checked,
  onChange,
  title,
  description,
  children,
}: ToggleProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={checked}
          onChange={(event) => {
            onChange(event.target.checked);
          }}
        />
        <span className="flex flex-col gap-0.5">
          <span className="text-sm font-medium">{title}</span>
          <span className="text-xs text-muted-foreground">{description}</span>
        </span>
      </label>
      {children !== undefined && (
        <div className="grid gap-3 pl-6 sm:grid-cols-2">{children}</div>
      )}
    </div>
  );
}

interface NumberFieldProps {
  id: string;
  label: string;
  value: string;
  message: string | null;
  onChange: (value: string) => void;
}

function NumberField({
  id,
  label,
  value,
  message,
  onChange,
}: NumberFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="numeric"
        value={value}
        aria-invalid={message !== null}
        aria-describedby={message ? `${id}-error` : undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      <FieldError id={`${id}-error`} message={message} />
    </div>
  );
}

/**
 * Receiver self-alerts (roadmap slice 088, issue #231): the station telling
 * the owner it is unhealthy — the message rate collapsing against this
 * hour-of-week's usual, the decoder staying down, a feeder going offline.
 *
 * Each condition raises one activity event and one browser notification per
 * episode and a "restored" one on recovery. The notifications take the same
 * path as alert matches, so the Notifications section's master switch and its
 * `High` severity switch govern them too (SPEC §48: browser only).
 *
 * Applies immediately: the backend monitor reads the section on every
 * sample, so there is no restart badge. Bounds mirror `SelfAlertSettings`.
 */
export function SelfAlertsSection({ config }: SelfAlertsSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickSelfAlerts(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  const share = fieldMessage(
    validateSelfAlertSharePct(draft.messageRateSharePct),
    fieldErrors["self_alerts.message_rate_share_pct"],
  );
  const rateMinutes = fieldMessage(
    validateSelfAlertRateMinutes(draft.messageRateMinutes),
    fieldErrors["self_alerts.message_rate_minutes"],
  );
  const decoderMinutes = fieldMessage(
    validateSelfAlertDecoderMinutes(draft.decoderDownMinutes),
    fieldErrors["self_alerts.decoder_down_minutes"],
  );

  function update(patch: Partial<SelfAlertsDraft>) {
    setDraft({ ...draft, ...patch });
  }

  function handleSave() {
    mutation.mutate(buildSelfAlertsPatch(draft), {
      onSuccess: (response) => {
        const next = pickSelfAlerts(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-self-alerts"
      title="Receiver self-alerts"
      description="Browser notifications when the station itself is unhealthy."
    >
      <div className="flex max-w-lg flex-col gap-3">
        <ConditionToggle
          checked={draft.decoderDownEnabled}
          onChange={(checked) => {
            update({ decoderDownEnabled: checked });
          }}
          title="Decoder disconnected"
          description="The decoder connection has been down for longer than this."
        >
          <NumberField
            id="settings-self-alerts-decoder-minutes"
            label="Down for longer than (minutes)"
            value={draft.decoderDownMinutes}
            message={decoderMinutes.message}
            onChange={(value) => {
              update({ decoderDownMinutes: value });
            }}
          />
        </ConditionToggle>

        <ConditionToggle
          checked={draft.messageRateEnabled}
          onChange={(checked) => {
            update({ messageRateEnabled: checked });
          }}
          title="Message rate collapsed"
          description="Messages per second below a share of what is usual for this weekday and hour. Needs two weeks of history before it can fire."
        >
          <NumberField
            id="settings-self-alerts-share"
            label="Below this share of usual (%)"
            value={draft.messageRateSharePct}
            message={share.message}
            onChange={(value) => {
              update({ messageRateSharePct: value });
            }}
          />
          <NumberField
            id="settings-self-alerts-rate-minutes"
            label="For at least (minutes)"
            value={draft.messageRateMinutes}
            message={rateMinutes.message}
            onChange={(value) => {
              update({ messageRateMinutes: value });
            }}
          />
        </ConditionToggle>

        <ConditionToggle
          checked={draft.feederOfflineEnabled}
          onChange={(checked) => {
            update({ feederOfflineEnabled: checked });
          }}
          title="Feeder offline"
          description="A network this receiver feeds went down (as on the Feeders page)."
        />

        <p className="text-xs text-muted-foreground">
          Delivered as browser notifications at High severity, so the
          Notifications section above must allow them.
        </p>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={
          share.blocking || rateMinutes.blocking || decoderMinutes.blocking
        }
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
