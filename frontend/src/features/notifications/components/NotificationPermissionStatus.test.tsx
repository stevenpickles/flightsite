import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationPermissionStatus } from "@/features/notifications/components/NotificationPermissionStatus";
import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { installNotificationMock } from "@/test/notificationMock";

beforeEach(() => {
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useNotificationStore.getState().reset();
});

describe("NotificationPermissionStatus", () => {
  it("offers the ask, and asks only when the button is clicked", async () => {
    const api = installNotificationMock({
      permission: "default",
      requestResult: "granted",
    });
    const user = userEvent.setup();
    render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByText(/browser permission: not requested/i),
    ).toBeVisible();
    // The heart of `docs/SECURITY.md` §5: rendering must not prompt.
    expect(api.requestPermission).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: /allow notifications/i }),
    );

    expect(api.requestPermission).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(/browser permission: allowed/i),
    ).toBeVisible();
  });

  it("shows the ask in flight, and does not ask twice while it is", async () => {
    // Headless Firefox does exactly this: it reports `default`, accepts the
    // request, and never settles it, because settling it is the prompt's job
    // and there is no prompt. A real user can also simply leave the prompt
    // sitting on screen. Either way the button must say so and refuse to
    // stack a second request behind the first.
    const api = installNotificationMock({ permission: "default" });
    api.requestPermission = vi.fn(
      () => new Promise<NotificationPermission>(() => {}),
    ) as unknown as typeof api.requestPermission;
    const user = userEvent.setup();
    render(<NotificationPermissionStatus enabled />);

    const ask = screen.getByRole("button", { name: /allow notifications/i });
    await user.click(ask);

    const pending = screen.getByRole("button", { name: /asking/i });
    expect(pending).toBeDisabled();
    expect(
      screen.getByText(/browser permission: not requested/i),
    ).toBeVisible();

    await user.click(pending);

    expect(api.requestPermission).toHaveBeenCalledTimes(1);
  });

  it("reports a denial the user just gave, and stops offering the button", async () => {
    installNotificationMock({ permission: "default", requestResult: "denied" });
    const user = userEvent.setup();
    render(<NotificationPermissionStatus enabled />);

    await user.click(
      screen.getByRole("button", { name: /allow notifications/i }),
    );

    expect(
      await screen.findByText(/browser permission: blocked/i),
    ).toBeVisible();
    // Browsers resolve a re-request immediately without prompting, so a
    // button here would look broken; the site-settings remedy is offered
    // instead.
    expect(
      screen.queryByRole("button", { name: /allow notifications/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/site settings/i)).toBeVisible();
  });

  it("explains a blocked permission on mount", () => {
    installNotificationMock({ permission: "denied" });
    render(<NotificationPermissionStatus enabled />);

    expect(screen.getByText(/browser permission: blocked/i)).toBeVisible();
  });

  it("publishes the state behind the prose for the E2E spec to compare", () => {
    // `e2e/tests/05-browser-notifications.spec.ts` asserts this attribute
    // against what the browser itself reports, so the two must keep the same
    // vocabulary — and a copy edit must not be able to fail that spec.
    installNotificationMock({ permission: "denied" });
    const { rerender } = render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByTestId("notification-permission-status"),
    ).toHaveAttribute("data-permission", "denied");

    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", false);
    useNotificationStore.getState().refreshPermission();
    rerender(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByTestId("notification-permission-status"),
    ).toHaveAttribute("data-permission", "insecure-context");
  });

  it("names the insecure-origin case rather than calling it unsupported", () => {
    // The most likely real-world cause: FlightSite reached over plain HTTP
    // on a LAN address (`docs/SECURITY.md` §1).
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", false);
    render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByText(/browser permission: unavailable on this address/i),
    ).toBeVisible();
    expect(screen.getByText(/HTTPS or on localhost/i)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /allow notifications/i }),
    ).not.toBeInTheDocument();
  });

  it("names an unsupported browser", () => {
    vi.stubGlobal("Notification", undefined);
    vi.stubGlobal("isSecureContext", true);
    render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByText(/browser permission: unavailable in this browser/i),
    ).toBeVisible();
  });

  it("points out a granted permission that the master switch is wasting", () => {
    installNotificationMock({ permission: "granted" });
    render(<NotificationPermissionStatus enabled={false} />);

    expect(screen.getByText(/switched off above/i)).toBeVisible();
  });

  it("surfaces what could not be shown", () => {
    installNotificationMock({ permission: "denied" });
    useNotificationStore.getState().recordSuppressed();
    render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByText(/1 alert this session could not be shown/i),
    ).toBeVisible();
  });

  it("pluralises the suppressed count and names the last error", () => {
    installNotificationMock({ permission: "granted" });
    useNotificationStore.getState().recordSuppressed();
    useNotificationStore.getState().recordError("constructor failed");
    render(<NotificationPermissionStatus enabled />);

    expect(
      screen.getByText(/2 alerts this session could not be shown/i),
    ).toBeVisible();
    expect(screen.getByText(/constructor failed/i)).toBeVisible();
  });

  it("re-reads the permission when the tab becomes visible again", async () => {
    // The user may have unblocked FlightSite in the browser's own site
    // settings while away from the tab.
    const api = installNotificationMock({ permission: "denied" });
    render(<NotificationPermissionStatus enabled />);
    expect(screen.getByText(/browser permission: blocked/i)).toBeVisible();

    api.permission = "granted";
    document.dispatchEvent(new Event("visibilitychange"));

    expect(
      await screen.findByText(/browser permission: allowed/i),
    ).toBeVisible();
  });
});
