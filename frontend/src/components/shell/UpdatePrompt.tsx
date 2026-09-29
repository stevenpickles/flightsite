/**
 * "A new version is available — Reload" (roadmap slice 084, issue #227): a
 * small, non-blocking card shown when a new deploy's service worker is
 * ready (`lib/pwa/registerServiceWorker.ts`).
 *
 * Non-blocking by design — not a dialog, no focus move, nothing behind it
 * made inert: a watcher mid-way through reading an aircraft's detail should
 * be told, not interrupted. The live region is `polite` and always mounted
 * (only its contents come and go), because a region inserted together with
 * its text is not reliably announced. Dismissing it hides it until the
 * next update is offered; nothing is applied without the Reload click.
 *
 * Rendered from `RootLayout`, so it reaches every route including the setup
 * wizard. Placed bottom-right from `md` up; on a phone it sits above the
 * Live Map's bottom toolbar rather than on top of it.
 */

import { RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useUpdateStore } from "@/lib/pwa/useUpdateStore";

export function UpdatePrompt() {
  const apply = useUpdateStore((state) => state.apply);
  const dismissed = useUpdateStore((state) => state.dismissed);
  const dismiss = useUpdateStore((state) => state.dismiss);
  const visible = apply !== null && !dismissed;

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-4 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] z-50 flex justify-center md:inset-x-auto md:bottom-4 md:right-4"
    >
      {visible && (
        <div
          data-testid="update-prompt"
          className="pointer-events-auto flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-card-foreground shadow-lg"
        >
          <RefreshCw
            className="size-4 shrink-0 text-accent"
            aria-hidden="true"
          />
          <span>A new version of FlightSite is available.</span>
          <Button type="button" size="sm" onClick={() => apply?.()}>
            Reload
          </Button>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss update notice"
            className="rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
