import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { QuickFilterChips } from "@/features/filters/components/QuickFilterChips";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";

beforeEach(() => {
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
});

describe("QuickFilterChips", () => {
  it("renders the Military chip disabled with an explanatory tooltip", async () => {
    render(<QuickFilterChips />);
    expect(screen.getByRole("button", { name: "Military" })).toBeDisabled();

    await userEvent.hover(screen.getByTestId("military-chip-trigger"));
    expect(
      await screen.findByText(/activates with aircraft metadata/i),
    ).toBeInTheDocument();
  });

  it("toggles emergency-only", async () => {
    render(<QuickFilterChips />);
    const chip = screen.getByRole("button", { name: "Emergency" });
    expect(chip).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.emergencyOnly).toBe(true);
    expect(chip).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.emergencyOnly).toBe(false);
  });

  it("toggles airborne-only via the ground-traffic filter", async () => {
    render(<QuickFilterChips />);
    const chip = screen.getByRole("button", { name: "Airborne only" });

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.groundTraffic).toBe("hide");
    expect(chip).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.groundTraffic).toBe("show");
  });

  it("reflects an externally-set ground mode as active", () => {
    useFilterStore.getState().setGroundTraffic("hide");
    render(<QuickFilterChips />);
    expect(
      screen.getByRole("button", { name: "Airborne only" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
