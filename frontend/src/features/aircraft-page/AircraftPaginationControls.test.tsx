import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";

describe("AircraftPaginationControls", () => {
  it("shows the page and total count, disabling Previous on page 1", () => {
    render(
      <AircraftPaginationControls
        page={1}
        pageSize={50}
        rowCount={50}
        total={137}
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
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
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
        onPageChange={onPageChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(onPageChange).toHaveBeenCalledWith(3);

    await user.click(screen.getByRole("button", { name: /previous/i }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });
});
