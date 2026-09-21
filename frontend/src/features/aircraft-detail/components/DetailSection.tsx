/**
 * A titled group of {@link FieldRow}s. Every section of the panel — Live,
 * Identity & metadata, and the phase 4/5 reserved sections — renders
 * through this so heading structure and spacing stay consistent, and so a
 * later slice adding a new section needs only this wrapper plus its rows.
 */

import type { ReactNode } from "react";

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
  return (
    <section className="border-t border-border px-4 py-3 first:border-t-0">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {description !== undefined && (
        <p className="mb-2 text-xs text-muted-foreground">{description}</p>
      )}
      <dl className="flex flex-col divide-y divide-border/60">{children}</dl>
    </section>
  );
}
