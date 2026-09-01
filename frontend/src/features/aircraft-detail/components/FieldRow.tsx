/**
 * One label/value row shared by every section of the detail panel.
 * `value === null` renders {@link UnknownValue} so a caller never has to
 * remember the null-vs-Unknown rule (§2.7) at each call site.
 */

import type { ReactNode } from "react";

import { ProvenanceIndicator } from "@/features/aircraft-detail/components/ProvenanceIndicator";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";

export interface FieldRowProps {
  label: string;
  value: ReactNode | null;
  /** Raw provenance source for this field, when the panel has one to show
   * (scope item 3). Omitted rows show no indicator at all — used for rows
   * that aren't part of the §3.3 provenance map (e.g. `on_ground`). */
  provenanceSource?: string;
}

export function FieldRow({ label, value, provenanceSource }: FieldRowProps) {
  const isUnknown = value === null || value === undefined;
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-1.5 text-right font-medium">
        {isUnknown ? <UnknownValue /> : value}
        {/* No provenance to show for a value that doesn't exist yet — the
         * indicator only makes sense once there's something to attribute. */}
        {!isUnknown && provenanceSource !== undefined && (
          <ProvenanceIndicator source={provenanceSource} />
        )}
      </dd>
    </div>
  );
}
