import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositionSourceBadge } from "@/features/aircraft-detail/components/PositionSourceBadge";
import type { PositionSource } from "@/lib/api/live";

describe("PositionSourceBadge", () => {
  it.each<[PositionSource, string]>([
    ["adsb", "ADS-B"],
    ["mlat", "MLAT"],
    ["none", "No position"],
    ["other", "Other"],
  ])("renders a text label for %s", (source, label) => {
    render(<PositionSourceBadge source={source} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
