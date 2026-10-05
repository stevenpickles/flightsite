/**
 * Marks something the receiver had never heard before the window being
 * shown: an aircraft, a type, or — on the log — the sighting an aircraft was
 * first heard in (slice 098). A worded pill rather than a bare star or a
 * colour, so it says what it means to a screen reader and in greyscale
 * (SPEC §36: never colour alone).
 */
export function NewBadge({ label = "New" }: { label?: string }) {
  return (
    <span
      data-testid="new-badge"
      className="inline-flex items-center gap-1 rounded-full border border-accent/60 bg-accent/10 px-2 py-0.5 text-xs font-semibold text-accent"
    >
      <span aria-hidden="true">★</span>
      {label}
    </span>
  );
}
