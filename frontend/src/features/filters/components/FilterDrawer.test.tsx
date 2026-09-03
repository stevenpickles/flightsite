import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilterDrawer } from "@/features/filters/components/FilterDrawer";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import type { MetadataStatusResponse } from "@/lib/api/metadata";
import { installMetadataApiMock, metadataSource } from "@/test/metadataApiMock";
import { renderWithProviders } from "@/test/test-utils";

/** One source with a dataset installed — the case where the drawer's
 * metadata-backed filters genuinely filter. */
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

beforeEach(() => {
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  // Default: a stock install with nothing imported, so the metadata-import
  // notes are present unless a test says otherwise.
  installMetadataApiMock({
    statusSequence: [
      {
        sources: [metadataSource({ name: "mictronics", status: "never-run" })],
      },
    ],
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The drawer reads metadata status through TanStack Query, so every render
 * needs a `QueryClientProvider` (roadmap slice 066). */
function renderDrawer() {
  return renderWithProviders(<FilterDrawer />);
}

describe("FilterDrawer", () => {
  it("starts closed and opens on toggle", async () => {
    renderDrawer();
    expect(screen.queryByTestId("filter-drawer")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByTestId("filter-drawer")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "Live map filters" }),
    ).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    expect(screen.getByTestId("filter-drawer")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByTestId("filter-drawer")).not.toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.click(
      screen.getByRole("button", { name: /close filters/i }),
    );
    expect(screen.queryByTestId("filter-drawer")).not.toBeInTheDocument();
  });

  it("shows no active-count badge with the defaults", () => {
    renderDrawer();
    expect(screen.queryByTestId("filter-active-count")).not.toBeInTheDocument();
  });

  it("updates the active-count badge as filters change and clears via Clear all", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));

    await userEvent.type(
      screen.getByLabelText(/callsign, registration, or icao/i),
      "BAW",
    );
    expect(screen.getByTestId("filter-active-count")).toHaveTextContent("1");
    expect(useFilterStore.getState().filters.liveSetQuery).toBe("BAW");

    await userEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(screen.queryByTestId("filter-active-count")).not.toBeInTheDocument();
    expect(useFilterStore.getState().filters).toEqual(DEFAULT_FILTERS);
  });

  it("edits the altitude range", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.type(screen.getByLabelText(/minimum altitude/i), "1000");
    expect(useFilterStore.getState().filters.altitudeMinFt).toBe(1000);

    await userEvent.type(screen.getByLabelText(/maximum altitude/i), "30000");
    expect(useFilterStore.getState().filters).toMatchObject({
      altitudeMinFt: 1000,
      altitudeMaxFt: 30000,
    });
  });

  it("edits the distance override", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.type(screen.getByLabelText(/maximum distance/i), "75");
    expect(useFilterStore.getState().filters.maxDistanceNm).toBe(75);
  });

  it("edits the category, operator, and operator-group text filters", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.type(screen.getByLabelText(/aircraft type/i), "737");
    await userEvent.type(screen.getByLabelText(/^operator$/i), "BAW");
    await userEvent.type(screen.getByLabelText(/operator group/i), "OW");
    expect(useFilterStore.getState().filters).toMatchObject({
      categoryText: "737",
      operatorText: "BAW",
      operatorGroupText: "OW",
    });
  });

  it("toggles emergency-only and interesting-only", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.click(
      screen.getByRole("checkbox", { name: /emergency squawk only/i }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /interesting only/i }),
    );
    expect(useFilterStore.getState().filters).toMatchObject({
      emergencyOnly: true,
      interestingOnly: true,
    });
  });

  it("toggles a classification checkbox and explains that it needs a metadata import", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Military" }));
    expect(useFilterStore.getState().filters.classifications).toEqual([
      "military",
    ]);
    expect(
      screen.getByText(/never guesses a classification/i),
    ).toHaveTextContent(/matches nothing until an aircraft-metadata import/i);
  });

  it("notes the missing import on every metadata-backed section when nothing is imported", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));

    // Category/operator, classification, and mission category.
    const notes = await screen.findAllByText(
      /matches nothing until an aircraft-metadata import runs \(settings → metadata\)/i,
    );
    expect(notes).toHaveLength(3);
  });

  it("drops the metadata-import notes once metadata is imported", async () => {
    installMetadataApiMock({ statusSequence: [IMPORTED] });
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));

    await waitFor(() =>
      expect(
        screen.queryByText(
          /matches nothing until an aircraft-metadata import/i,
        ),
      ).not.toBeInTheDocument(),
    );
    // The filters themselves are untouched — only the caveat goes away.
    expect(screen.getByRole("checkbox", { name: "Military" })).toBeEnabled();
    expect(screen.getByLabelText(/aircraft type/i)).toBeEnabled();
  });

  it("adds and removes a mission category chip", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    const input = screen.getByLabelText(/add mission category/i);
    await userEvent.type(input, "medevac{enter}");
    expect(useFilterStore.getState().filters.missionCategories).toEqual([
      "medevac",
    ]);

    await userEvent.click(screen.getByRole("button", { name: /medevac ✕/i }));
    expect(useFilterStore.getState().filters.missionCategories).toEqual([]);
  });

  it("selects a ground-traffic mode from the segmented control", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    const group = screen.getByRole("radiogroup", { name: /ground traffic/i });
    await userEvent.click(within(group).getByRole("radio", { name: "Dim" }));
    expect(useFilterStore.getState().filters.groundTraffic).toBe("dim");
  });

  it("toggles hide-stale and hide-non-positioned checkboxes", async () => {
    renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /filters/i }));
    await userEvent.click(
      screen.getByRole("checkbox", { name: /hide stale aircraft/i }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /hide non-positioned aircraft/i }),
    );
    expect(useFilterStore.getState().filters.hideStale).toBe(true);
    expect(useFilterStore.getState().filters.hideNonPositioned).toBe(true);
  });
});
