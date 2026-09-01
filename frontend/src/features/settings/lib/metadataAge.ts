/**
 * The overall "metadata last updated" figure (roadmap slice 025), computed
 * from per-source status rather than stored anywhere of its own — it is
 * always the max `last_success_ms` across sources, so a fresh install where
 * nothing has ever run reads as `null` rather than a fabricated zero. Slice
 * 042's health/diagnostics surface reads this same age.
 */
import type { MetadataSourceStatusEntry } from "@/lib/api/metadata";

/** The most recent successful import across every source, in epoch
 * milliseconds — or `null` when no source has ever completed one, which is
 * the honest "never" state a fresh install starts in (§2.7 null/unknown
 * semantics: absence, not a guess). */
export function overallMetadataAge(
  sources: readonly MetadataSourceStatusEntry[],
): number | null {
  const successes = sources
    .map((source) => source.last_success_ms)
    .filter((value): value is number => value !== null);
  return successes.length === 0 ? null : Math.max(...successes);
}
