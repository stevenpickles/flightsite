/**
 * One-line classification summary — shared by the live detail panel, the
 * non-live detail page and the Aircraft page table's Classification column,
 * so all three read a classification the same way (roadmap slice 029).
 */

import { missionLabel } from "@/features/aircraft-detail/lib/missionLabels";
import type { Classification } from "@/lib/api/live";

/** `"Military · Military"`, `"Government, Law enforcement · Government"`, or
 * `"Civilian · Commercial passenger"` — the flag set (or `"Civilian"` when
 * none is set) followed by the human mission label. `null` (§2.7: no
 * classification asserts anything) renders as nothing here; callers show
 * {@link UnknownValue `Unknown`} for a `null` field the usual way. */
export function classificationSummary(
  classification: Classification | null,
): string | null {
  if (classification === null) {
    return null;
  }
  const flags: string[] = [];
  if (classification.military) flags.push("Military");
  if (classification.government) flags.push("Government");
  if (classification.law_enforcement) flags.push("Law enforcement");
  const base = flags.length > 0 ? flags.join(", ") : "Civilian";
  return `${base} · ${missionLabel(classification.mission)}`;
}
