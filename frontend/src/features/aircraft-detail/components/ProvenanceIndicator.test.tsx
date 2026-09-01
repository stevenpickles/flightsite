import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ProvenanceIndicator } from "@/features/aircraft-detail/components/ProvenanceIndicator";

function renderIndicator(source: string) {
  return render(
    <TooltipProvider>
      <ProvenanceIndicator source={source} />
    </TooltipProvider>,
  );
}

describe("ProvenanceIndicator", () => {
  it("carries the plain-language description in an accessible label", () => {
    renderIndicator("aerodatabox");
    expect(
      screen.getByRole("button", {
        name: /Source: AeroDataBox\. Looked up from the AeroDataBox/i,
      }),
    ).toBeInTheDocument();
  });

  it("falls back gracefully for an undocumented future source", () => {
    renderIndicator("brand_new_provider");
    expect(
      screen.getByRole("button", { name: /Source: Brand New Provider/i }),
    ).toBeInTheDocument();
  });
});
