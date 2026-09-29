import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UpdatePrompt } from "@/components/shell/UpdatePrompt";
import { useUpdateStore } from "@/lib/pwa/useUpdateStore";

beforeEach(() => {
  useUpdateStore.setState({ apply: null, dismissed: false });
});

describe("UpdatePrompt", () => {
  it("shows nothing until an update is offered, inside an always-mounted polite live region", () => {
    const { container } = render(<UpdatePrompt />);
    expect(screen.queryByTestId("update-prompt")).not.toBeInTheDocument();
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  it("offers the new version and applies it only on Reload", async () => {
    const user = userEvent.setup();
    const apply = vi.fn();
    render(<UpdatePrompt />);

    act(() => {
      useUpdateStore.getState().offer(apply);
    });
    expect(
      screen.getByText("A new version of FlightSite is available."),
    ).toBeInTheDocument();
    expect(apply).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(apply).toHaveBeenCalledOnce();
  });

  it("can be dismissed until the next offer", async () => {
    const user = userEvent.setup();
    render(<UpdatePrompt />);
    act(() => {
      useUpdateStore.getState().offer(vi.fn());
    });

    await user.click(
      screen.getByRole("button", { name: "Dismiss update notice" }),
    );
    expect(screen.queryByTestId("update-prompt")).not.toBeInTheDocument();

    act(() => {
      useUpdateStore.getState().offer(vi.fn());
    });
    expect(screen.getByTestId("update-prompt")).toBeInTheDocument();
  });
});
