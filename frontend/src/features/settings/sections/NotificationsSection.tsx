import { useState } from "react";

import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildNotificationsPatch,
  draftFromConfig,
  isSectionDirty,
  pickNotifications,
} from "@/features/settings/lib/draft";
import { generalErrorMessage } from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig, NotificationConfig } from "@/lib/api/config";

export interface NotificationsSectionProps {
  config: FlightSiteConfig;
}

const SEVERITY_OPTIONS: readonly {
  key: keyof Omit<NotificationConfig, "enabled">;
  label: string;
  description: string;
}[] = [
  {
    key: "critical",
    label: "Critical",
    description: "Emergency squawks and the most severe matches.",
  },
  {
    key: "high",
    label: "High",
    description: "Significant matches worth an immediate look.",
  },
  {
    key: "interesting",
    label: "Interesting",
    description: "Everyday interesting-aircraft matches.",
  },
  {
    key: "info",
    label: "Info",
    description: "Low-signal, informational-only matches.",
  },
];

/** Browser notification preferences: a master switch plus one toggle per
 * alert severity (SPEC §46/§48). Applies immediately. */
export function NotificationsSection({ config }: NotificationsSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickNotifications(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors: Record<string, string> = {};

  function setNotification(patch: Partial<NotificationConfig>) {
    setDraft({ notifications: { ...draft.notifications, ...patch } });
  }

  function handleSave() {
    mutation.mutate(buildNotificationsPatch(draft), {
      onSuccess: (response) => {
        const next = pickNotifications(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-notifications"
      title="Notifications"
      description="Browser notifications, per alert severity."
    >
      <div className="flex max-w-lg flex-col gap-4">
        <label className="flex items-start gap-3 rounded-lg border border-border p-3">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={draft.notifications.enabled}
            onChange={(event) => {
              setNotification({ enabled: event.target.checked });
            }}
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">
              Enable browser notifications
            </span>
            <span className="text-xs text-muted-foreground">
              Once per sighting per matched alert rule (SPEC §48).
            </span>
          </span>
        </label>

        <fieldset
          disabled={!draft.notifications.enabled}
          className="flex flex-col gap-2 disabled:opacity-50"
        >
          <legend className="mb-1 text-sm font-medium">
            Notify for severity
          </legend>
          {SEVERITY_OPTIONS.map((option) => (
            <label key={option.key} className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={draft.notifications[option.key]}
                onChange={(event) => {
                  setNotification({ [option.key]: event.target.checked });
                }}
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm">{option.label}</span>
                <span className="text-xs text-muted-foreground">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={false}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
