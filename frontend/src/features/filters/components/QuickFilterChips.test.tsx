import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilterDrawer } from "@/features/filters/components/FilterDrawer";
import { QuickFilterChips } from "@/features/filters/components/QuickFilterChips";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import type { MetadataStatusResponse } from "@/lib/api/metadata";
import { installMetadataApiMock, metadataSource } from "@/test/metadataApiMock";
import { renderWithProviders } from "@/test/test-utils";

/** A status document reporting one source with a dataset installed — the
 * "metadata available" case the Military chip is gated on. */
const IMPORTED: MetadataStatusResponse = {
  sources: [
    metadataSource({
      name: "mictronics",
      status: "ok",
      row_count: 412_003,
      last_success_ms: 1_756_600_000_000,
      dataset_version: "2026-08-01",
    }),
  ],
};

/** A stock install: the source is registered, but nothing has been imported. */
const NOT_IMPORTED: MetadataStatusResponse = {
  sources: [metadataSource({ name: "mictronics", status: "never-run" })],
};

beforeEach(() => {
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  installMetadataApiMock({ statusSequence: [NOT_IMPORTED] });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function militaryChip() {
  return screen.getByRole("button", { name: "Military" });
}

describe("QuickFilterChips", () => {
  it("keeps the Military chip disabled with a tooltip pointing at Settings when no metadata is imported", async () => {
    renderWithProviders(<QuickFilterChips />);
    expect(militaryChip()).toBeDisabled();

    await userEvent.hover(screen.getByTestId("military-chip-trigger"));
    // Radix renders the content plus a visually-hidden copy for assistive
    // tech, so both carry the wording — assert on the set, not on one node.
    const tooltip = await screen.findAllByText(
      /no aircraft metadata imported yet/i,
    );
    expect(tooltip.length).toBeGreaterThan(0);
    expect(tooltip[0]).toHaveTextContent(/settings → metadata/i);
    // Still disabled after the status has settled — no enable-then-disable.
    expect(militaryChip()).toBeDisabled();
  });

  it("enables the Military chip and toggles the military classification once metadata is imported", async () => {
    installMetadataApiMock({ statusSequence: [IMPORTED] });
    renderWithProviders(<QuickFilterChips />);

    await waitFor(() => expect(militaryChip()).toBeEnabled());
    expect(militaryChip()).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(militaryChip());
    expect(useFilterStore.getState().filters.classifications).toEqual([
      "military",
    ]);
    expect(militaryChip()).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(militaryChip());
    expect(useFilterStore.getState().filters.classifications).toEqual([]);
    expect(militaryChip()).toHaveAttribute("aria-pressed", "false");
  });

  it("reflects an externally-set military classification as active", async () => {
    installMetadataApiMock({ statusSequence: [IMPORTED] });
    useFilterStore.getState().toggleClassification("military");
    renderWithProviders(<QuickFilterChips />);

    await waitFor(() => expect(militaryChip()).toBeEnabled());
    expect(militaryChip()).toHaveAttribute("aria-pressed", "true");
  });

  it("mirrors the drawer's Military checkbox in both directions", async () => {
    installMetadataApiMock({ statusSequence: [IMPORTED] });
    renderWithProviders(
      <>
        <QuickFilterChips />
        <FilterDrawer />
      </>,
    );
    await waitFor(() => expect(militaryChip()).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: /^filters$/i }));

    const checkbox = screen.getByRole("checkbox", { name: "Military" });
    await userEvent.click(militaryChip());
    expect(checkbox).toBeChecked();

    await userEvent.click(checkbox);
    expect(militaryChip()).toHaveAttribute("aria-pressed", "false");
    expect(useFilterStore.getState().filters.classifications).toEqual([]);
  });

  it("keeps the Military chip disabled while the metadata status is still loading", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    renderWithProviders(<QuickFilterChips />);
    expect(militaryChip()).toBeDisabled();
  });

  it("keeps the Military chip disabled when the metadata status request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("network down"))),
    );
    renderWithProviders(<QuickFilterChips />);

    // Give the failed query a chance to settle: the safe state must survive it.
    await waitFor(() => expect(militaryChip()).toBeDisabled());
    expect(screen.getByTestId("military-chip-trigger")).toBeInTheDocument();
  });

  it("toggles emergency-only", async () => {
    renderWithProviders(<QuickFilterChips />);
    const chip = screen.getByRole("button", { name: "Emergency" });
    expect(chip).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.emergencyOnly).toBe(true);
    expect(chip).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.emergencyOnly).toBe(false);
  });

  it("toggles airborne-only via the ground-traffic filter", async () => {
    renderWithProviders(<QuickFilterChips />);
    const chip = screen.getByRole("button", { name: "Airborne only" });

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.groundTraffic).toBe("hide");
    expect(chip).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(chip);
    expect(useFilterStore.getState().filters.groundTraffic).toBe("show");
  });

  it("reflects an externally-set ground mode as active", () => {
    useFilterStore.getState().setGroundTraffic("hide");
    renderWithProviders(<QuickFilterChips />);
    expect(
      screen.getByRole("button", { name: "Airborne only" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
