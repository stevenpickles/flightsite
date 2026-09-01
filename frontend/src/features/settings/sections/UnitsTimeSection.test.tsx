import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnitsTimeSection } from "@/features/settings/sections/UnitsTimeSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    units: "aviation",
    timezone: "Europe/London",
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <UnitsTimeSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UnitsTimeSection", () => {
  it("renders prefilled units and timezone", () => {
    installConfigApiMock();
    renderSection();

    expect(screen.getByRole("radio", { name: /aviation/i })).toBeChecked();
    expect(screen.getByLabelText(/timezone/i)).toHaveValue("Europe/London");
  });

  it("saves a changed unit system", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("radio", { name: /metric/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({ units: "metric", timezone: "Europe/London" });
  });
});
