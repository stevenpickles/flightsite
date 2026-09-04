import { RotateCw } from "lucide-react";

/** The one wording the whole Settings page uses for this, so a section
 * header and a single field never phrase the same promise differently. */
export const RESTART_REQUIRED_LABEL = "Applies on next restart";

export interface RestartRequiredBadgeProps {
  /** Set when the badge annotates a single field rather than a whole
   * section: point that field's `aria-describedby` at this id so a screen
   * reader hears the caveat while the field has focus. Without it the badge
   * is plain text beside the heading it qualifies, which is how the
   * section-level badge is already announced. */
  id?: string;
}

/**
 * "Applies on next restart", as a chip.
 *
 * Shared deliberately: `SettingsSection` renders it for a section whose every
 * setting is restart-required (Decoder, Receiver, Retention), and a section
 * that mixes both kinds (Units &amp; time, Aircraft Metadata) renders the
 * identical chip under the one field that waits. Same wording, same styling,
 * one component — a second, hand-rolled inline note is how the two drift
 * apart.
 */
export function RestartRequiredBadge({ id }: RestartRequiredBadgeProps) {
  return (
    <span
      id={id}
      className="inline-flex w-fit items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
    >
      <RotateCw className="size-3" aria-hidden="true" />
      {RESTART_REQUIRED_LABEL}
    </span>
  );
}
