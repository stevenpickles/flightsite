import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmergencySquawkBadge } from "@/features/aircraft-detail/components/EmergencySquawkBadge";

describe("EmergencySquawkBadge", () => {
  it.each([
    ["7500", "Hijack"],
    ["7600", "Radio failure"],
    ["7700", "General emergency"],
  ])("labels %s with its plain-language meaning", (squawk, meaning) => {
    render(<EmergencySquawkBadge squawk={squawk} />);
    expect(
      screen.getByText(new RegExp(`${squawk}.*${meaning}`)),
    ).toBeInTheDocument();
  });

  it("falls back to a generic label for an unrecognized code", () => {
    render(<EmergencySquawkBadge squawk="9999" />);
    expect(screen.getByText(/9999.*Emergency/)).toBeInTheDocument();
  });
});
