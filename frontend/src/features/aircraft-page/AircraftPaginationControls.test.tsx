import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";

/** The invariant-plural case the footer used to hardcode. */
const AIRCRAFT = { singular: "aircraft", plural: "aircraft" };
/** A noun that actually inflects, which "aircraft" hid. */
const SIGHTINGS = { singular: "sighting", plural: "sightings" };

describe("AircraftPaginationControls", () => {
  it("shows the page and total count, disabling Previous on page 1", () => {
    render(
      <AircraftPaginationControls
        page={1}
        pageSize={50}
        rowCount={50}
        total={137}
        noun={AIRCRAFT}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Page 1 of 3 · 137 aircraft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
  });

  it("disables Next on the last page", () => {
    render(
      <AircraftPaginationControls
        page={3}
        pageSize={50}
        rowCount={37}
        total={137}
        noun={AIRCRAFT}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("falls back to a page-only label and a full-page heuristic when total is omitted (§2.4)", () => {
    const onPageChange = vi.fn();
    render(
      <AircraftPaginationControls
        page={2}
        pageSize={50}
        rowCount={50}
        total={null}
        noun={AIRCRAFT}
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
  });

  it("treats a short page as the last one when total is omitted", () => {
    render(
      <AircraftPaginationControls
        page={2}
        pageSize={50}
        rowCount={12}
        total={null}
        noun={AIRCRAFT}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("counts what the page actually lists, not always aircraft", () => {
    // Issue #112: this footer is shared by /aircraft, /sightings and
    // /activity, and used to say "aircraft" on all three.
    render(
      <AircraftPaginationControls
        page={1}
        pageSize={50}
        rowCount={50}
        total={137}
        noun={SIGHTINGS}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Page 1 of 3 · 137 sightings")).toBeInTheDocument();
  });

  it("uses the singular for a count of exactly one", () => {
    // "aircraft" is invariant, so the old hardcoded label happened to read
    // correctly at any count; "sighting" is not, and one row must not say
    // "1 sightings".
    render(
      <AircraftPaginationControls
        page={1}
        pageSize={50}
        rowCount={1}
        total={1}
        noun={SIGHTINGS}
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Page 1 of 1 · 1 sighting")).toBeInTheDocument();
  });

  it("reports the target page on click", async () => {
    const onPageChange = vi.fn();
    const user = userEvent.setup();
    render(
      <AircraftPaginationControls
        page={2}
        pageSize={50}
        rowCount={50}
        total={137}
        noun={AIRCRAFT}
        onPageChange={onPageChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(onPageChange).toHaveBeenCalledWith(3);

    await user.click(screen.getByRole("button", { name: /previous/i }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });
});
