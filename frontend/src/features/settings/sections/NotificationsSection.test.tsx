import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationsSection } from "@/features/settings/sections/NotificationsSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig();
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationsSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
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
});
