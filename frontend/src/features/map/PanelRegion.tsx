import type { ReactNode } from "react";

/**
 * A floating card's landmark, wrapped around it from the page rather than
 * edited into the card itself (R1-11): a `<section>` with an accessible
 * name computes to the ARIA `region` role, and the `<h2>` inside gives every
 * card a place in the page's heading hierarchy — previously just
 * `["H1: Live Map"]`, with the Basemap, Layers, Interesting, Non-positioned,
 * Activity and Today cards all unlabelled `div`s with a `button` header and
 * no heading or landmark route to any of them. `label` is visually hidden
 * (`sr-only`): every one of these cards already shows its own name in its
 * toggle button or header, so the heading exists for screen-reader
 * navigation without printing the name twice on screen.
 *
 * Lifted out of `LiveMapPage` in roadmap slice 084 so the phone layout
 * (`phone/PhoneMapControls`) wraps its docked cards in the same landmarks.
 */
export function PanelRegion({
  headingId,
  label,
  className,
  children,
}: {
  headingId: string;
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section role="region" aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="sr-only">
        {label}
      </h2>
      {children}
    </section>
  );
}
