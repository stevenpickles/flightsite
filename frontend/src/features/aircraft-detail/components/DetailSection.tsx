/**
 * A titled group of {@link FieldRow}s. Every section of the panel — Live,
 * Identity & metadata, and the phase 4/5 reserved sections — renders
 * through this so heading structure and spacing stay consistent, and so a
 * later slice adding a new section needs only this wrapper plus its rows.
 */

import type { ReactNode } from "react";

export interface DetailSectionProps {
  title: string;
  children: ReactNode;
}

export function DetailSection({ title, children }: DetailSectionProps) {
  return (
    <section className="border-t border-border px-4 py-3 first:border-t-0">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <dl className="flex flex-col divide-y divide-border/60">{children}</dl>
    </section>
  );
}
