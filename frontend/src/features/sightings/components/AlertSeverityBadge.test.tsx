import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import type { AlertSeverity } from "@/lib/api/sightings";

describe("AlertSeverityBadge", () => {
  it.each<[AlertSeverity, string]>([
    ["info", "Info"],
    ["interesting", "Interesting"],
    ["high", "High"],
    ["critical", "Critical"],
  ])("renders the %s severity as %s text", (severity, label) => {
    render(<AlertSeverityBadge severity={severity} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
