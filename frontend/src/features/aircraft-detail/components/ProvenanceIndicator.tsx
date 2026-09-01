/**
 * Unobtrusive per-field provenance indicator (scope item 3): a small dot
 * that names its source on hover/focus. It is a real, focusable button with
 * an `aria-label` carrying the full sentence, so the source is available to
 * assistive tech without depending on the tooltip being visible — the dot
 * itself is decorative, never the only place the information lives.
 */

import { describeProvenance } from "@/features/aircraft-detail/lib/provenance";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface ProvenanceIndicatorProps {
  /** Raw provenance value, or `undefined`/`"decoder"` for a decoder-direct
   * field (§2.6: a field with no entry in the map is decoder-direct). */
  source: string;
}

export function ProvenanceIndicator({ source }: ProvenanceIndicatorProps) {
  const info = describeProvenance(source);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex size-3.5 shrink-0 items-center justify-center rounded-full",
            "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          )}
          aria-label={`Source: ${info.label}. ${info.description}`}
        >
          <span
            aria-hidden="true"
            className={cn(
              "size-1.5 rounded-full",
              info.source === "decoder"
                ? "bg-muted-foreground/50"
                : "bg-accent",
            )}
          />
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <p className="max-w-56 text-xs">
          <span className="font-medium">{info.label}</span> — {info.description}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}
