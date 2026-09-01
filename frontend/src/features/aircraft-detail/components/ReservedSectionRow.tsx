/**
 * Quiet placeholder for a section whose data plumbing doesn't exist yet
 * (scope item 5: Route — slice 026, Nearest airport — slice 027,
 * History/lifetime records — slice 029-era). Rendering the section now,
 * empty, means a later slice only has to add data and swap this row for
 * real {@link FieldRow}s — no structural change to the panel.
 */
export interface ReservedSectionRowProps {
  note: string;
}

export function ReservedSectionRow({ note }: ReservedSectionRowProps) {
  return <p className="py-1 text-sm italic text-muted-foreground">{note}</p>;
}
