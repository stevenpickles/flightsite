import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { ReviewStep } from "@/features/setup/steps/ReviewStep";
import { INITIAL_DECODER_TEST_STATE } from "@/features/setup/types";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig({
    location: {
      latitude: 47.6,
      longitude: -122.3,
      site_name: "Home Roof",
      antenna_height_ft: null,
    },
    alerts: { enabled_templates: ["military", "watchlist"] },
  }),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("ReviewStep", () => {
  it("summarizes the collected values", () => {
    render(
      <ReviewStep
        draft={draft}
        testState={{ status: "success", skipped: false, message: "ok" }}
        hasStoredKey={false}
        submitError={null}
      />,
    );
    expect(screen.getByText("Home Roof")).toBeInTheDocument();
    expect(screen.getByText("47.6, -122.3")).toBeInTheDocument();
    expect(
      screen.getByText(/127\.0\.0\.1:8080\/data\/aircraft\.json/),
    ).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText(/military.*watchlist/i)).toBeInTheDocument();
    // R4-16: says what a selected template actually becomes, rather than
    // implying the selection is itself the ongoing setting.
    expect(
      screen.getByText(/becomes a rule on the alerts page/i),
    ).toBeInTheDocument();
  });

  it("says nothing about templates becoming rules when none are selected (R4-16)", () => {
    const noTemplates = { ...draft, enabledTemplateIds: [] };
    render(
      <ReviewStep
        draft={noTemplates}
        testState={INITIAL_DECODER_TEST_STATE}
        hasStoredKey={false}
        submitError={null}
      />,
    );
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.queryByText(/becomes a rule on the alerts page/i)).toBeNull();
  });

  it("shows Skipped/Not tested/Failed decoder status appropriately", () => {
    const { rerender } = render(
      <ReviewStep
        draft={draft}
        testState={INITIAL_DECODER_TEST_STATE}
        hasStoredKey={false}
        submitError={null}
      />,
    );
    expect(screen.getByText("Not tested")).toBeInTheDocument();

    rerender(
      <ReviewStep
        draft={draft}
        testState={{ status: "idle", skipped: true, message: null }}
        hasStoredKey={false}
        submitError={null}
      />,
    );
    expect(screen.getByText("Skipped")).toBeInTheDocument();

    rerender(
      <ReviewStep
        draft={draft}
        testState={{ status: "error", skipped: false, message: "Unreachable" }}
        hasStoredKey={false}
        submitError={null}
      />,
    );
    expect(screen.getByText(/failed \(will still save\)/i)).toBeInTheDocument();
  });

  it("reports the AeroDataBox key as set when a stored key exists and was not cleared", () => {
    render(
      <ReviewStep
        draft={draft}
        testState={INITIAL_DECODER_TEST_STATE}
        hasStoredKey
        submitError={null}
      />,
    );
    expect(screen.getByText("Set")).toBeInTheDocument();
  });

  it("shows a submit error when present", () => {
    render(
      <ReviewStep
        draft={draft}
        testState={INITIAL_DECODER_TEST_STATE}
        hasStoredKey={false}
        submitError="Could not save configuration."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      /could not save configuration/i,
    );
  });
});
