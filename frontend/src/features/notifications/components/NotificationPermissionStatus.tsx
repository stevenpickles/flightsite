/**
 * The browser's side of the notification story, made visible (roadmap slice
 * 040): what this browser currently allows, the button that asks it, and what
 * FlightSite could not show because it said no.
 *
 * Rendered inside the Notifications settings section — the place
 * `docs/SECURITY.md` §5 names as one of the two opt-in surfaces, and the one
 * the roadmap requires the request to be *re-promptable* from. Slice 042's
 * health area shows the same permission from the same store
 * (`docs/PRODUCT.md` §4.11).
 *
 * Each unhappy state gets its own sentence rather than a shared "unavailable",
 * because the remedies are entirely different: a blocked permission is fixed
 * in the browser's site settings, while an insecure origin cannot be fixed
 * there at all. The insecure case is not hypothetical — FlightSite is normally
 * reached over plain HTTP on a LAN address (`docs/SECURITY.md` §1), and every
 * current browser withholds the Notification API outside HTTPS or `localhost`.
 */

import { BellOff, BellRing, ShieldAlert } from "lucide-react";

import { useNotificationPermission } from "@/features/notifications/useNotificationPermission";
import { canRequest } from "@/features/notifications/lib/permission";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { Button } from "@/components/ui/button";

export interface NotificationPermissionStatusProps {
  /** The saved master preference. When notifications are switched off, the
   * permission is reported but not chased — asking a browser for a permission
   * the user has just declined to use would be noise. */
  enabled: boolean;
}

interface StatusCopy {
  label: string;
  detail: string;
  tone: "ok" | "warn" | "muted";
}

function statusCopy(
  permission: ReturnType<typeof useNotificationPermission>["permission"],
): StatusCopy {
  switch (permission) {
    case "granted":
      return {
        label: "Allowed",
        detail:
          "This browser will show FlightSite alert notifications, including while the tab is in the background.",
        tone: "ok",
      };
    case "denied":
      return {
        label: "Blocked",
        detail:
          "This browser is blocking notifications for FlightSite. Allow them in the browser's site settings for this address (usually the icon at the left of the address bar), then reload.",
        tone: "warn",
      };
    case "insecure-context":
      return {
        label: "Unavailable on this address",
        detail:
          "Browsers only offer notifications over HTTPS or on localhost. FlightSite is open over plain HTTP, so the Notification API is not available here — everything else about alerts (the map, the interesting panel, the activity feed) is unaffected.",
        tone: "warn",
      };
    case "unsupported":
      return {
        label: "Unavailable in this browser",
        detail:
          "This browser does not support the Notification API. Alerts still appear in the interesting-aircraft panel and the activity feed.",
        tone: "warn",
      };
    default:
      return {
        label: "Not requested",
        detail:
          "FlightSite has not asked this browser for permission yet. It will ask only when you choose to.",
        tone: "muted",
      };
  }
}

const TONE_CLASS: Record<StatusCopy["tone"], string> = {
  ok: "text-accent-foreground",
  warn: "text-destructive",
  muted: "text-muted-foreground",
};

export function NotificationPermissionStatus({
  enabled,
}: NotificationPermissionStatusProps) {
  const { permission, isRequesting, request } = useNotificationPermission();
  const suppressed = useNotificationStore((state) => state.suppressed);
  const lastError = useNotificationStore((state) => state.lastError);
  const copy = statusCopy(permission);
  const Icon =
    permission === "granted"
      ? BellRing
      : permission === "denied"
        ? ShieldAlert
        : BellOff;

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-border bg-muted/30 p-3"
      data-testid="notification-permission-status"
    >
      <div className="flex items-start justify-between gap-3">
        <div
          role="status"
          aria-live="polite"
          className="flex items-start gap-2"
        >
          <Icon
            className={`mt-0.5 size-4 shrink-0 ${TONE_CLASS[copy.tone]}`}
            aria-hidden="true"
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">
              Browser permission: {copy.label}
            </span>
            <span className="text-xs text-muted-foreground">{copy.detail}</span>
          </span>
        </div>
        {canRequest(permission) && (
          <Button
            type="button"
            variant="accent"
            size="sm"
            disabled={isRequesting}
            onClick={() => {
              // Fired straight from the click: `requestPermission()` needs the
              // user activation this handler still holds (lib/permission.ts).
              void request();
            }}
          >
            {isRequesting ? "Asking…" : "Allow notifications"}
          </Button>
        )}
      </div>

      {permission === "granted" && !enabled && (
        <p className="text-xs text-muted-foreground">
          Notifications are switched off above, so nothing will be shown even
          though the browser allows it.
        </p>
      )}

      {suppressed > 0 && (
        <p className="text-xs text-destructive">
          {suppressed === 1
            ? "1 alert this session could not be shown as a notification."
            : `${suppressed.toLocaleString()} alerts this session could not be shown as notifications.`}
          {lastError === null ? "" : ` Last error: ${lastError}`}
        </p>
      )}
    </div>
  );
}
