/**
 * The Live Map's own surfacing of browser-notification permission (R1-12).
 *
 * Before this, `NotificationPermissionStatus` — the full explanation of what
 * the browser currently allows, the request button, and the suppressed-alert
 * count — was reachable only from the Notifications settings section
 * (`grep` for its name finds exactly one importer). A user who skipped or
 * dismissed the setup wizard's notification step, or whose browser has the
 * permission blocked, gets an emergency-squawk match delivered nowhere: no
 * browser notification (correctly — `dispatch.ts` never prompts unprompted,
 * per `docs/SECURITY.md` §5) and, until now, no hint on the map itself that
 * anything was missed. `dispatch.ts` already counts these as suppressed
 * (`useNotificationStore.suppressed`); this component is the first thing on
 * the Live Map that reads that counter.
 *
 * Deliberately quiet the same way `ConnectionStatusChip` is: a granted
 * permission is the healthy, common case and renders nothing at all. Every
 * other state — not yet asked, blocked, or the two ways the API can be
 * absent — gets a compact, one-line pill: a short reason, the inline
 * re-promptable "Enable" button where a click could still change the answer
 * (`canRequest`, `default` only — a `denied` re-request resolves without a
 * prompt, so the same reasoning `NotificationPermissionStatus` uses applies
 * here too), and a link to Settings for the fuller explanation and the
 * per-severity preferences this pill has no room for.
 *
 * Reuses `useNotificationPermission` (never prompts on its own — the request
 * only ever fires from this component's own button click, preserving the
 * user activation `requestNotificationPermission` needs) and
 * `useNotificationStore` for the suppressed count, rather than re-deriving
 * either.
 */

import { BellOff, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";

import {
  canRequest,
  type NotificationPermissionState,
} from "@/features/notifications/lib/permission";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { useNotificationPermission } from "@/features/notifications/useNotificationPermission";
import { cn } from "@/lib/utils";

const MESSAGE: Record<
  Exclude<NotificationPermissionState, "granted">,
  string
> = {
  default: "Browser notifications are off.",
  denied: "Browser notifications are blocked.",
  "insecure-context": "Notifications need HTTPS or localhost.",
  unsupported: "This browser can't show notifications.",
};

function suppressedPrefix(suppressed: number): string | null {
  if (suppressed === 0) {
    return null;
  }
  return suppressed === 1
    ? "1 alert not notified"
    : `${suppressed.toLocaleString()} alerts not notified`;
}

export function NotificationStatusPill() {
  const { permission, isRequesting, request } = useNotificationPermission();
  const suppressed = useNotificationStore((state) => state.suppressed);

  if (permission === "granted") {
    return null;
  }

  const prefix = suppressedPrefix(suppressed);
  const message = MESSAGE[permission];

  return (
    <div
      role="status"
      data-testid="notification-status-pill"
      data-permission={permission}
      className={cn(
        "pointer-events-auto absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 flex-wrap items-center gap-x-2 gap-y-1",
        "max-w-[min(28rem,92vw)] rounded-full border border-border bg-card/95 px-3 py-1.5",
        "text-[11px] font-medium text-muted-foreground shadow-md backdrop-blur-sm",
      )}
    >
      {permission === "denied" ? (
        <ShieldAlert
          className="size-3.5 shrink-0 text-destructive"
          aria-hidden="true"
        />
      ) : (
        <BellOff className="size-3.5 shrink-0" aria-hidden="true" />
      )}
      <span>{prefix === null ? message : `${prefix} — ${message}`}</span>
      {canRequest(permission) && (
        <button
          type="button"
          disabled={isRequesting}
          onClick={() => {
            // Fired straight from the click: `requestPermission()` needs the
            // user activation this handler still holds.
            void request();
          }}
          className="rounded-md border border-border px-1.5 py-0.5 text-[11px] font-medium text-foreground outline-none transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {isRequesting ? "Asking…" : "Enable"}
        </button>
      )}
      <Link
        to="/settings"
        className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-accent underline-offset-2 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        Settings
      </Link>
    </div>
  );
}
