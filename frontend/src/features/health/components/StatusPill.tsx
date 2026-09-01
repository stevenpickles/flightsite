import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  HelpCircle,
  type LucideIcon,
  XCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The presentation vocabulary for every health state on the page.
 *
 * `unknown` is a first-class tone rather than a fallback: SPEC §67 has several
 * items that are legitimately unknowable on a fresh install (no integrity
 * check has run, no metadata has been imported), and rendering those as either
 * healthy or broken would be a lie.
 */
export type StatusTone = "ok" | "warn" | "bad" | "unknown" | "idle";

const TONE_PRESENTATION: Record<
  StatusTone,
  { icon: LucideIcon; className: string }
> = {
  ok: { icon: CheckCircle2, className: "text-accent-foreground" },
  warn: {
    icon: AlertTriangle,
    className: "text-amber-600 dark:text-amber-500",
  },
  bad: { icon: XCircle, className: "text-destructive" },
  unknown: { icon: HelpCircle, className: "text-muted-foreground" },
  idle: { icon: CircleSlash, className: "text-muted-foreground" },
};

interface StatusPillProps {
  tone: StatusTone;
  label: string;
  className?: string;
}

/**
 * An icon-plus-text status badge.
 *
 * SPEC §80 forbids colour as the only carrier of meaning, so the icon and the
 * word are the signal and the tint is decoration — the badge still reads
 * correctly in greyscale, and `data-tone` gives tests something stable to
 * assert on that is not a colour class.
 */
export function StatusPill({ tone, label, className }: StatusPillProps) {
  const { icon: Icon, className: toneClass } = TONE_PRESENTATION[tone];
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-semibold",
        toneClass,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden={true} />
      {label}
    </span>
  );
}
