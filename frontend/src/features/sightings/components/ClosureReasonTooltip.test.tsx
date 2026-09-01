import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import type { ClosureReason } from "@/lib/api/sightings";

function renderTooltip(reason: ClosureReason) {
  return render(
    <TooltipProvider>
      <ClosureReasonTooltip reason={reason} />
    </TooltipProvider>,
  );
}

describe("ClosureReasonTooltip", () => {
  it("renders the plain-language label for gap_timeout", () => {
    renderTooltip("gap_timeout");
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("renders the plain-language label for shutdown_recovery", () => {
    renderTooltip("shutdown_recovery");
    expect(screen.getByText("Recovered at restart")).toBeInTheDocument();
  });

  it("renders the plain-language label for data_reset", () => {
    renderTooltip("data_reset");
    expect(screen.getByText("Data reset")).toBeInTheDocument();
  });
});
