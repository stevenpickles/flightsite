import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SelfAlertsSection } from "@/features/settings/sections/SelfAlertsSection";
import type { FlightSiteConfig } from "@/lib/api/config";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection(config: FlightSiteConfig = defaultFlightSiteConfig()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SelfAlertsSection config={config} />
    </QueryClientProvider>,
  );
}

function putBodies(fetchMock: ReturnType<typeof vi.fn>): unknown[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT")
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SelfAlertsSection", () => {
  it("renders every toggle and threshold from the config", () => {
    installConfigApiMock();
    renderSection();

    expect(
      screen.getByRole("checkbox", { name: /decoder disconnected/i }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /message rate collapsed/i }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /feeder offline/i }),
    ).toBeChecked();
    expect(
      screen.getByLabelText(/down for longer than \(minutes\)/i),
    ).toHaveValue("5");
    expect(screen.getByLabelText(/share of usual \(%\)/i)).toHaveValue("40");
    expect(screen.getByLabelText(/for at least \(minutes\)/i)).toHaveValue(
      "15",
    );
    // Applies on save: no restart badge.
    expect(
      screen.queryByText(/applies on next restart/i),
    ).not.toBeInTheDocument();
  });

  it("falls back to the documented defaults for an older backend", () => {
    installConfigApiMock();
    const legacy = defaultFlightSiteConfig();
    delete legacy.self_alerts;
    renderSection(legacy);
    expect(screen.getByLabelText(/share of usual/i)).toHaveValue("40");
  });

  it.each([
    [/share of usual/i, "3", /whole percentage between 5 and 95/i],
    [/share of usual/i, "40.5", /whole percentage between 5 and 95/i],
    [/for at least/i, "4", /minutes between 5 and 240/i],
    [/down for longer than \(minutes\)/i, "0", /minutes between 1 and 240/i],
    [/down for longer than \(minutes\)/i, "241", /minutes between 1 and 240/i],
  ])(
    "blocks Save for an out-of-range value (%s = %s)",
    async (label, value, message) => {
      installConfigApiMock();
      const user = userEvent.setup();
      renderSection();

      const input = screen.getByLabelText(label);
      await user.clear(input);
      await user.type(input, value);

      expect(screen.getByText(message)).toBeInTheDocument();
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    },
  );

  it("saves the whole section", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("checkbox", { name: /feeder offline/i }));
    const minutes = screen.getByLabelText(/down for longer than \(minutes\)/i);
    await user.clear(minutes);
    await user.type(minutes, "10");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    expect(putBodies(fetchMock)).toEqual([
      {
        self_alerts: {
          message_rate_enabled: true,
          message_rate_share_pct: 40,
          message_rate_minutes: 15,
          decoder_down_enabled: true,
          decoder_down_minutes: 10,
          feeder_offline_enabled: false,
        },
      },
    ]);
  });
});
