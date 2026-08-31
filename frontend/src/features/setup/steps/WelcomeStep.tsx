import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { validateSiteName } from "@/features/setup/lib/validation";
import type { WizardDraft } from "@/features/setup/types";

export interface WelcomeStepProps {
  draft: WizardDraft;
  isFirstRun: boolean;
  onChange: (patch: Partial<WizardDraft>) => void;
}

/** Step (a): welcome and site name — the only field this step collects.
 * Step-level validity (whether Next may be pressed) is derived from
 * `draft` alone by `isStepValid` in the parent, not reported up from here —
 * this component only needs the error for its own inline message. */
export function WelcomeStep({ draft, isFirstRun, onChange }: WelcomeStepProps) {
  const error = validateSiteName(draft.siteName);

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          {isFirstRun ? "Welcome to FlightSite" : "Update your setup"}
        </h2>
        <p className="text-sm text-muted-foreground">
          {isFirstRun
            ? "A few steps to connect your receiver and get the Live Map showing what it sees. You can change any of this later from Settings."
            : "Re-running the wizard preloads everything from your current configuration — change only what you need, then finish to save it."}
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="setup-site-name">Site name</Label>
        <Input
          id="setup-site-name"
          value={draft.siteName}
          maxLength={120}
          placeholder="e.g. Home Roof Antenna"
          aria-invalid={error !== null}
          aria-describedby={error ? "setup-site-name-error" : undefined}
          onChange={(event) => {
            onChange({ siteName: event.target.value });
          }}
        />
        <p className="text-xs text-muted-foreground">
          Shown throughout FlightSite to identify this receiver.
        </p>
        <FieldError id="setup-site-name-error" message={error} />
      </div>
    </div>
  );
}
