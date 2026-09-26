import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { HealthCard } from "@/features/health/components/HealthCard";
import type { FeederLocalPage } from "@/lib/api/feeders";

interface LocalPagesCardProps {
  localPages: readonly FeederLocalPage[];
}

/** Links to the sibling pages hosted beside FlightSite (tar1090,
 * graphs1090, SkyAware, the FR24 feeder UI, …) — design record context: "the
 * owner … runs sibling pages beside FlightSite … [n]one of that is visible
 * in FlightSite". */
export function LocalPagesCard({ localPages }: LocalPagesCardProps) {
  return (
    // `data-testid="local-pages-card"` per `e2e/tests/12-feeders.spec.ts`'s
    // convention.
    <div data-testid="local-pages-card">
      <HealthCard
        titleId="feeders-local-pages"
        title="Local pages"
        description="Other tools hosted alongside FlightSite."
      >
        {localPages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No local pages configured — add them in{" "}
            <Link
              to="/settings#settings-feeders"
              className="underline-offset-4 hover:underline"
            >
              Settings
            </Link>
            .
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {localPages.map((page) => (
              <li key={page.url}>
                <a
                  href={page.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                >
                  {page.label}
                  <ExternalLink className="size-3.5" aria-hidden="true" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </HealthCard>
    </div>
  );
}
