import type { NotificationConfig } from "@/lib/api/config";
import type { WizardDraft } from "@/features/setup/types";

export interface NotificationsStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
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

/**
 * Step (e): the browser notification preference only. This step never calls
 * `Notification.requestPermission()` — it records what the user wants, and
 * the wizard's Finish button is what asks the browser, once, if this
 * preference is on (slice 040, `docs/SECURITY.md` §5: requested only after
 * the user opts in, never unprompted). Asking from the Finish click rather
 * than from this step also means the prompt cannot appear behind a user who
 * is still deciding, and that it carries the user activation Firefox and
 * Safari require.
 */
export function NotificationsStep({ draft, onChange }: NotificationsStepProps) {
  function setNotification(patch: Partial<NotificationConfig>) {
    onChange({ notifications: { ...draft.notifications, ...patch } });
  }

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          Browser notifications
        </h2>
        <p className="text-sm text-muted-foreground">
          If you turn these on, FlightSite asks your browser for permission
          once, when you finish setup. You can change your mind, and ask again,
          in Settings.
        </p>
      </div>

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
  );
}
