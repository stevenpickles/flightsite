import { DetailRow, HealthCard } from "@/features/health/components/HealthCard";
import { StatusPill } from "@/features/health/components/StatusPill";
import { notificationPresentation } from "@/features/health/lib/status";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { useNotificationPermission } from "@/features/notifications/useNotificationPermission";
import type { DiagnosticsNotifications } from "@/lib/api/diagnostics";

interface NotificationHealthCardProps {
  notifications: DiagnosticsNotifications;
}

/**
 * SPEC §67's notification permission/status — the one item on this page the
 * backend genuinely cannot supply.
 *
 * The server knows which severities the user asked for; only the browser
 * knows whether it is allowed to show them, and only this session knows how
 * many it actually delivered. Slice 040's store already tracks both, so this
 * reads it rather than re-deriving the permission (its module docstring
 * names slice 042 as the consumer).
 *
 * Read-only by design: `docs/SECURITY.md` §5 requires the permission prompt
 * to originate from a click on one of the two opt-in surfaces (the setup
 * wizard, the Notifications settings section), so this card reports and
 * links, and never asks.
 */
export function NotificationHealthCard({
  notifications,
}: NotificationHealthCardProps) {
  const { permission } = useNotificationPermission();
  const delivered = useNotificationStore((state) => state.delivered);
  const suppressed = useNotificationStore((state) => state.suppressed);
  const lastError = useNotificationStore((state) => state.lastError);

  const presentation = notificationPresentation(
    permission,
    notifications.configured_enabled,
  );
  const enabledSeverities = Object.entries(notifications.severities)
    .filter(([, enabled]) => enabled)
    .map(([severity]) => severity);

  return (
    <HealthCard
      titleId="health-notifications"
      title="Browser notifications"
      description="Permission is a browser fact — the server cannot see it."
      status={
        <StatusPill tone={presentation.tone} label={presentation.label} />
      }
    >
      <div
        data-testid="health-notification-permission"
        data-permission={permission}
      >
        <DetailRow
          label="Enabled in settings"
          value={notifications.configured_enabled ? "Yes" : "No"}
        />
        <DetailRow
          label="Severities"
          value={
            enabledSeverities.length > 0 ? enabledSeverities.join(", ") : "None"
          }
        />
        <DetailRow label="Delivered this session" value={delivered} />
        <DetailRow label="Suppressed this session" value={suppressed} />
        {lastError !== null && (
          <p className="mt-2 text-xs text-destructive">
            Last delivery error: {lastError}
          </p>
        )}
        {permission === "denied" && (
          <p className="mt-2 text-xs text-muted-foreground">
            Your browser is blocking notifications for this site. Alerts are
            still recorded in the activity feed and alert history.
          </p>
        )}
      </div>
    </HealthCard>
  );
}
