/**
 * Renders a sighting's `closure_reason` as its plain-language label, with a
 * tooltip carrying the full explanation — SPEC §57 asks for the log to
 * communicate why a sighting closed (gap timeout vs. shutdown recovery) in
 * words, not just the raw vocabulary slug.
 */

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { describeClosureReason } from "@/features/sightings/lib/format";
import type { ClosureReason } from "@/lib/api/sightings";

export interface ClosureReasonTooltipProps {
  reason: ClosureReason;
}

export function ClosureReasonTooltip({ reason }: ClosureReasonTooltipProps) {
  const info = describeClosureReason(reason);
  if (info === null) {
    return null;
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className="cursor-help text-sm underline decoration-dotted decoration-muted-foreground/60 underline-offset-2 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {info.label}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="max-w-64 text-xs">{info.description}</p>
      </TooltipContent>
    </Tooltip>
  );
}
