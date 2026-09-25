/**
 * A titled group of {@link FieldRow}s. Every section of the panel — Live,
 * Identity & metadata, and the phase 4/5 reserved sections — renders
 * through this so heading structure and spacing stay consistent, and so a
 * later slice adding a new section needs only this wrapper plus its rows.
 */

import { createContext, useContext, type ReactNode } from "react";

/**
 * The heading level this section's title renders at (review R2-17).
 *
 * A detail *route* puts these sections directly under its `<h1>`, so they
 * are `<h2>`; the review found `/aircraft/:icao` going `H1` → `H3` with no
 * `H2` anywhere, because this component hard-coded `h3`. The *panel* is
 * different: its own title is an `<h2>` (it is a labelled dialog), so its
 * sections genuinely are one level further down.
 *
 * Context rather than a prop, because the sections are reached through
 * shared wrappers — `IdentityMetadataSection`, `LifetimeSection`,
 * `NearestAirportSection` — and threading a level through each of them
 * would make every one of them care about a question only its host can
 * answer.
 */
const HeadingLevelContext = createContext<2 | 3>(2);

export interface DetailSectionHeadingLevelProps {
  level: 2 | 3;
  children: ReactNode;
}

/** Wraps a subtree whose `DetailSection` headings should render at `level`.
 * Unwrapped, they are `<h2>` — the right answer under a route's `<h1>`. */
export function DetailSectionHeadingLevel({
  level,
  children,
}: DetailSectionHeadingLevelProps) {
  return (
    <HeadingLevelContext.Provider value={level}>
      {children}
    </HeadingLevelContext.Provider>
  );
}

export interface DetailSectionProps {
  title: string;
  /** One line under the heading, for a section whose content needs saying
   * something about — what a drawn path actually is, for instance (review
   * R2-12). Rendered outside the `<dl>`, since it describes the section
   * rather than being one of its rows. */
  description?: ReactNode;
  children: ReactNode;
}

export function DetailSection({
  title,
  description,
  children,
}: DetailSectionProps) {
  const Heading = useContext(HeadingLevelContext) === 2 ? "h2" : "h3";
  return (
    <section className="border-t border-border px-4 py-3 first:border-t-0">
      <Heading className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </Heading>
      {description !== undefined && (
        <p className="mb-2 text-xs text-muted-foreground">{description}</p>
      )}
      <dl className="flex flex-col divide-y divide-border/60">{children}</dl>
    </section>
  );
}
