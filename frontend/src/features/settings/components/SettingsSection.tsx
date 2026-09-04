import type { ReactNode } from "react";

import { RestartRequiredBadge } from "@/features/settings/components/RestartRequiredBadge";

export interface SettingsSectionProps {
  id: string;
  title: string;
  description: string;
  /** Shown when *every* setting in this section only takes effect after the
   * backend restarts — the decoder endpoint and receiver location, which a
   * running ingestion loop and live store hold for their lifetime (see
   * `flightsite.api.ingestion`), and the high-resolution metric window, read
   * once when the metrics service is built. This is about *changing* a
   * value: a fresh install's first save starts ingestion in place, which is
   * why the setup wizard makes no such promise.
   *
   * A section where only some settings wait leaves this off and renders
   * `RestartRequiredBadge` under the fields that do. */
  restartRequired?: boolean;
  children: ReactNode;
}

/**
 * One collapsible settings section — a native `<details>` disclosure, which
 * gets keyboard operation (Enter/Space on the `<summary>`) and screen-reader
 * semantics for free instead of a hand-rolled accordion. Defaults open, so
 * the page reads as stacked cards until a user chooses to collapse one.
 */
export function SettingsSection({
  id,
  title,
  description,
  restartRequired = false,
  children,
}: SettingsSectionProps) {
  return (
    <details
      id={id}
      open
      className="group rounded-lg border border-border bg-card"
    >
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-4 [&::-webkit-details-marker]:hidden">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {restartRequired && <RestartRequiredBadge />}
          </div>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
        <span
          aria-hidden="true"
          className="mt-1 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        >
          ▾
        </span>
      </summary>
      <div className="flex flex-col gap-4 border-t border-border px-4 py-4">
        {children}
      </div>
    </details>
  );
}
