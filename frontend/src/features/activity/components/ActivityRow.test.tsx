import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ActivityRow } from "@/features/activity/components/ActivityRow";
import type { ActivityEvent } from "@/lib/api/activity";
import { activityEvent } from "@/test/activityApiMock";

function renderRow(event: ActivityEvent, timezone = "UTC") {
  return render(
    <MemoryRouter>
      <ul>
        <ActivityRow event={event} timezone={timezone} />
      </ul>
    </MemoryRouter>,
  );
}

describe("ActivityRow", () => {
  it("links an aircraft-scoped event to that airframe", () => {
    renderRow(activityEvent({ icao: "ae1463", sighting_id: 88213 }));

    // The airframe wins over the sighting: a feed row about an aircraft is a
    // row the user follows to that aircraft.
    expect(
      screen.getByRole("link", { name: "First ever sighting" }),
    ).toHaveAttribute("href", "/aircraft/ae1463");
  });

  it("links a sighting-scoped event with no airframe to the sighting", () => {
    renderRow(
      activityEvent({
        type: "receiver_record",
        icao: null,
        sighting_id: 9021,
        payload: { record: "longest_sighting", duration_s: 8040 },
      }),
    );

    expect(
      screen.getByRole("link", { name: "New longest sighting" }),
    ).toHaveAttribute("href", "/sightings/9021");
  });

  it("renders a receiver-wide event as plain text, linking nowhere", () => {
    renderRow(
      activityEvent({
        type: "receiver_offline",
        icao: null,
        sighting_id: null,
        payload: { error: "connection refused" },
      }),
    );

    expect(screen.getByText("Receiver went offline")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the time in the receiver's zone, not the browser's", () => {
    renderRow(
      activityEvent({ at: "2026-08-31T14:03:22.418Z" }),
      "America/New_York",
    );

    // 14:03 UTC is 10:03 in New York on 31 August (EDT).
    expect(screen.getByText("10:03")).toBeInTheDocument();
  });

  it("omits the detail line when the event has nothing to add", () => {
    const { container } = renderRow(
      activityEvent({
        type: "receiver_restored",
        icao: null,
        sighting_id: null,
        payload: {},
      }),
    );

    expect(screen.getByText("Receiver back online")).toBeInTheDocument();
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });
});
