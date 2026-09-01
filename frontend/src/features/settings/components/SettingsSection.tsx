import { RotateCw } from "lucide-react";
import type { ReactNode } from "react";

export interface SettingsSectionProps {
  id: string;
  title: string;
  description: string;
  /** Shown when a change in this section only takes effect after the
   * backend restarts (SPEC: ingestion reads the receiver endpoint and
   * location once at process startup — see `flightsite.app`). */
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
            {restartRequired && (
              <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                <RotateCw className="size-3" aria-hidden="true" />
                Applies on next restart
              </span>
            )}
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
