import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { NotificationsSection } from "@/features/settings/sections/NotificationsSection";
import type { FlightSiteConfig } from "@/lib/api/config";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";
import { installNotificationMock } from "@/test/notificationMock";

function renderSection(overrides: Partial<FlightSiteConfig> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = { ...defaultFlightSiteConfig(), ...overrides };
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationsSection config={config} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useNotificationStore.getState().reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  useNotificationStore.getState().reset();
});

describe("NotificationsSection", () => {
  it("renders the master switch and per-severity toggles from the current config", () => {
    installConfigApiMock();
    renderSection();

    expect(
      screen.getByRole("checkbox", { name: /enable browser notifications/i }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^info/i })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^critical/i })).toBeChecked();
  });

  it("disables severity toggles when the master switch is off", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("checkbox", { name: /enable browser notifications/i }),
    );

    expect(screen.getByRole("checkbox", { name: /^critical/i })).toBeDisabled();
  });

  it("saves the toggled notification preferences", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("checkbox", { name: /^info/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      notifications: {
        enabled: true,
        info: true,
        interesting: true,
        high: true,
        critical: true,
      },
    });
  });

  it("shows the browser permission alongside the preferences", () => {
    installConfigApiMock();
    installNotificationMock({ permission: "granted" });
    renderSection();

    expect(
      screen.getByTestId("notification-permission-status"),
    ).toBeInTheDocument();
    expect(screen.getByText(/browser permission: allowed/i)).toBeVisible();
  });

  it("never asks the browser just because the section rendered", () => {
    installConfigApiMock();
    const api = installNotificationMock({ permission: "default" });
    renderSection();

    expect(api.requestPermission).not.toHaveBeenCalled();
  });

  it("asks the browser when the user saves with notifications on", async () => {
    // Saving an enabled preference is the opt-in `docs/SECURITY.md` §5
    // requires before a permission request, and the click is the user
    // activation the browser requires.
    installConfigApiMock();
    const api = installNotificationMock({
      permission: "default",
      requestResult: "granted",
    });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("checkbox", { name: /^info/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.requestPermission).toHaveBeenCalledTimes(1);
  });

  it("does not ask when the user saves with notifications switched off", async () => {
    installConfigApiMock();
    const api = installNotificationMock({ permission: "default" });
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("checkbox", { name: /enable browser notifications/i }),
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.requestPermission).not.toHaveBeenCalled();
  });

  it("does not re-ask a browser that has already answered", async () => {
    installConfigApiMock();
    const api = installNotificationMock({ permission: "denied" });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("checkbox", { name: /^info/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.requestPermission).not.toHaveBeenCalled();
  });
});
