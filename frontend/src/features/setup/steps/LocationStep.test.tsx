import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { draftFromConfig } from "@/features/setup/lib/draft";
import { LocationStep } from "@/features/setup/steps/LocationStep";
import { defaultFlightSiteConfig } from "@/test/configApiMock";
import { getLastMockMap, resetMapLibreMock } from "@/test/maplibreGlMock";

const draft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig(),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

beforeEach(() => {
  resetMapLibreMock();
});

describe("LocationStep", () => {
  it("renders the map picker alongside the manual inputs", () => {
    render(<LocationStep draft={draft} onChange={vi.fn()} />);
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
    expect(screen.getByLabelText(/latitude/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/longitude/i)).toBeInTheDocument();
  });

  it("shows validation errors for out-of-range coordinates", () => {
    render(
      <LocationStep
        draft={{ ...draft, latitude: "200", longitude: "-200" }}
        onChange={vi.fn()}
      />,
    );
    const alerts = screen.getAllByRole("alert");
    expect(alerts.length).toBeGreaterThanOrEqual(2);
  });

  it("reports manual latitude/longitude edits via onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <LocationStep draft={{ ...draft, latitude: "" }} onChange={onChange} />,
    );

    await user.type(screen.getByLabelText(/latitude/i), "5");
    expect(onChange).toHaveBeenCalledWith({ latitude: "5" });
  });

  it("clicking the map reports the clicked position, rounded to 5 decimals", () => {
    const onChange = vi.fn();
    render(<LocationStep draft={draft} onChange={onChange} />);

    act(() => {
      getLastMockMap().emit("click", {
        lngLat: { lat: 47.123456, lng: -122.654321 },
      });
    });

    expect(onChange).toHaveBeenCalledWith({
      latitude: "47.12346",
      longitude: "-122.65432",
    });
  });

  it("validates the optional antenna height", () => {
    render(
      <LocationStep
        draft={{ ...draft, antennaHeightFt: "50000" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/between -1400 and 30000/i)).toBeInTheDocument();
  });

  it("accepts a blank antenna height", () => {
    render(
      <LocationStep
        draft={{ ...draft, antennaHeightFt: "" }}
        onChange={vi.fn()}
      />,
    );
    expect(
      screen.queryByText(/between -1400 and 30000/i),
    ).not.toBeInTheDocument();
  });
});
