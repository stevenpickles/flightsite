import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DecoderSection } from "@/features/settings/sections/DecoderSection";
import {
  defaultFlightSiteConfig,
  failureConnectionTestResult,
  installConfigApiMock,
  successConnectionTestResult,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig();
  return render(
    <QueryClientProvider client={queryClient}>
      <DecoderSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DecoderSection", () => {
  it("renders prefilled from the current config", () => {
    installConfigApiMock();
    renderSection();

    expect(screen.getByLabelText(/host/i)).toHaveValue("127.0.0.1");
    expect(screen.getByLabelText(/port/i)).toHaveValue("8080");
    expect(screen.getByLabelText(/path/i)).toHaveValue("/data/aircraft.json");
    expect(screen.getByLabelText(/poll interval/i)).toHaveValue("1");
  });

  it("runs a successful connection test and shows the result", async () => {
    installConfigApiMock({
      decoderTestResult: successConnectionTestResult({
        aircraft_count: 42,
        positioned_count: 30,
        flavor: "readsb",
      }),
    });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText(/connected — found readsb, 42 aircraft/i),
    ).toBeInTheDocument();
  });

  it("runs a failed connection test and shows the failure detail", async () => {
    installConfigApiMock({
      decoderTestResult: failureConnectionTestResult({
        detail: "Connection refused",
      }),
    });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText(/unreachable: connection refused/i),
    ).toBeInTheDocument();
  });

  it("resets a stale test result once a tested field changes", async () => {
    installConfigApiMock({ decoderTestResult: successConnectionTestResult() });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /test connection/i }));
    await screen.findByText(/connected — found/i);

    await user.type(screen.getByLabelText(/host/i), "x");
    expect(screen.queryByText(/connected — found/i)).not.toBeInTheDocument();
  });

  it("saves the edited decoder endpoint and sends the expected payload", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/port/i));
    await user.type(screen.getByLabelText(/port/i), "8081");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls).toHaveLength(1);
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      receiver: {
        host: "127.0.0.1",
        port: 8081,
        path: "/data/aircraft.json",
        poll_interval_s: 1,
      },
    });
  });

  it("blocks Save and Test connection with an inline error for an invalid port", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/port/i));
    await user.type(screen.getByLabelText(/port/i), "0");

    expect(
      screen.getByText(/enter a port between 1 and 65535/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /test connection/i }),
    ).toBeDisabled();
  });
});
