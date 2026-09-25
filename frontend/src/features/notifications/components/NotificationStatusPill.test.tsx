import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationStatusPill } from "@/features/notifications/components/NotificationStatusPill";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { installNotificationMock } from "@/test/notificationMock";

function renderPill() {
  return render(
    <MemoryRouter>
      <NotificationStatusPill />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useNotificationStore.getState().reset();
});

describe("NotificationStatusPill", () => {
  it("renders nothing at all once permission is granted — the quiet, healthy case", () => {
    installNotificationMock({ permission: "granted" });
    renderPill();
    expect(
      screen.queryByTestId("notification-status-pill"),
    ).not.toBeInTheDocument();
  });

  it("offers to enable notifications, and asks only on click", async () => {
    const api = installNotificationMock({
      permission: "default",
      requestResult: "granted",
    });
    renderPill();

    expect(screen.getByText(/browser notifications are off/i)).toBeVisible();
    expect(api.requestPermission).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /enable/i }));
    expect(api.requestPermission).toHaveBeenCalledTimes(1);
    // Granted disappears the pill entirely, same as a fresh mount would.
    await waitFor(() => {
      expect(
        screen.queryByTestId("notification-status-pill"),
      ).not.toBeInTheDocument();
    });
  });

  it("names a blocked permission and offers no re-request button", async () => {
    installNotificationMock({ permission: "denied" });
    renderPill();

    expect(
      screen.getByText(/browser notifications are blocked/i),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /enable/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("names the insecure-origin case", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", false);
    renderPill();

    expect(
      screen.getByText(/notifications need https or localhost/i),
    ).toBeVisible();
  });

  it("names an unsupported browser", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", true);
    renderPill();

    expect(
      screen.getByText(/this browser can't show notifications/i),
    ).toBeVisible();
  });

  it("leads with the suppressed count when alerts were missed", () => {
    installNotificationMock({ permission: "denied" });
    useNotificationStore.getState().recordSuppressed();
    useNotificationStore.getState().recordSuppressed();
    renderPill();

    expect(
      screen.getByText(
        /2 alerts not notified — browser notifications are blocked/i,
      ),
    ).toBeVisible();
  });

  it("singularizes one suppressed alert", () => {
    installNotificationMock({ permission: "denied" });
    useNotificationStore.getState().recordSuppressed();
    renderPill();

    expect(screen.getByText(/^1 alert not notified/i)).toBeVisible();
  });

  it("publishes the permission behind the pill for tooling to key off of", () => {
    installNotificationMock({ permission: "denied" });
    renderPill();
    expect(screen.getByTestId("notification-status-pill")).toHaveAttribute(
      "data-permission",
      "denied",
    );
  });
});
