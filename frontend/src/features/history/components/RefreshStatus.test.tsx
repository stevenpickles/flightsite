import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RefreshStatus } from "@/features/history/components/RefreshStatus";

describe("RefreshStatus", () => {
  it("names how old the data on screen is", () => {
    render(
      <RefreshStatus
        updatedAt={Date.now() - 12_000}
        isFetching={false}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Updated 12s ago")).toBeInTheDocument();
  });

  it("says so rather than claiming an age before anything has loaded", () => {
    render(
      <RefreshStatus updatedAt={0} isFetching={false} onRefresh={vi.fn()} />,
    );

    expect(screen.getByText("Not loaded yet")).toBeInTheDocument();
  });

  it("asks for a refetch when the control is used", async () => {
    const onRefresh = vi.fn();
    const user = userEvent.setup();
    render(
      <RefreshStatus
        updatedAt={Date.now()}
        isFetching={false}
        onRefresh={onRefresh}
      />,
    );

    await user.click(screen.getByRole("button", { name: /refresh/i }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("reports a request in flight instead of a stale age, and blocks a second one", () => {
    render(
      <RefreshStatus
        updatedAt={Date.now() - 60_000}
        isFetching
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Updating…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeDisabled();
  });

  it("names the automatic cadence, so an unasked-for change has an explanation", () => {
    render(
      <RefreshStatus
        updatedAt={Date.now()}
        isFetching={false}
        onRefresh={vi.fn()}
        intervalMs={15_000}
      />,
    );

    expect(screen.getByRole("button", { name: /refresh/i })).toHaveAttribute(
      "title",
      "Refreshes automatically every 15s",
    );
  });

  it("promises no cadence on a page that does not poll", () => {
    render(
      <RefreshStatus
        updatedAt={Date.now()}
        isFetching={false}
        onRefresh={vi.fn()}
        intervalMs={null}
      />,
    );

    expect(screen.getByRole("button", { name: /refresh/i })).toHaveAttribute(
      "title",
      "Fetch the latest data now",
    );
  });
});
