/**
 * The sidebar's Health nav item roll-up status dot (roadmap slice 082, SPEC
 * §80). Reuses the exact hook and presentation vocabulary `HealthPage`
 * itself reads from — `useDiagnosticsQuery` and `overallPresentation` — so
 * the dot can never disagree with the page it summarizes; it is a second
 * *view* of the same roll-up, never a second opinion computed independently.
 *
 * A colour-only dot would fail SPEC §80's "severity communicated by text as
 * well as color", so the coloured dot itself is `aria-hidden` and always
 * paired with a visually-hidden status word that becomes part of the
 * "Health" link's accessible name, plus a `title` for a mouse-hover tooltip.
 */
import { overallPresentation } from "@/features/health/lib/status";
import type { StatusTone } from "@/features/health/components/StatusPill";
import { useDiagnosticsQuery } from "@/lib/api/diagnostics";
import { cn } from "@/lib/utils";

const DOT_TONE_CLASSES: Record<StatusTone, string> = {
  ok: "bg-success-on-surface",
  warn: "bg-amber-500",
  bad: "bg-destructive",
  unknown: "bg-muted-foreground",
  idle: "bg-muted-foreground",
};

export function HealthStatusDot() {
  const diagnosticsQuery = useDiagnosticsQuery();
  const status = diagnosticsQuery.data?.status;

  // No opinion until the first successful load — `HealthPage` itself makes
  // no stronger claim before then (its loading/error states render first).
  if (status === undefined) {
    return null;
  }

  const { tone, label } = overallPresentation(status);

  return (
    <span
      className="inline-flex shrink-0 items-center"
      title={`Health: ${label}`}
      data-testid="health-status-dot"
      data-tone={tone}
    >
      <span
        aria-hidden="true"
        className={cn("size-1.5 rounded-full", DOT_TONE_CLASSES[tone])}
      />
      <span className="sr-only">{` (${label})`}</span>
    </span>
  );
}
