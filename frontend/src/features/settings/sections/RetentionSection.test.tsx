import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RetentionSection } from "@/features/settings/sections/RetentionSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    retention: { high_res_metric_days: 14 },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RetentionSection", () => {
  it("renders the current retention window", () => {
    installConfigApiMock();
    renderSection();
    expect(screen.getByLabelText(/retention/i)).toHaveValue("14");
  });

  it("shows the restart-required badge", () => {
    // The metrics service reads the window when it is constructed, so the
    // sweep keeps the old one until the backend restarts
    // (docs/CONFIGURATION.md, "Which settings need a restart").
    installConfigApiMock();
    renderSection();
    expect(screen.getByText(/applies on next restart/i)).toBeInTheDocument();
  });

  it("blocks Save outside the 7-30 day bounds", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/retention/i));
    await user.type(screen.getByLabelText(/retention/i), "31");

    expect(
      screen.getByText(/enter a whole number of days between 7 and 30/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("saves an in-range retention window", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/retention/i));
    await user.type(screen.getByLabelText(/retention/i), "21");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({ retention: { high_res_metric_days: 21 } });
  });

  it("keeps Save enabled after a rejected save so the user can retry (R4-02)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ["retention", "high_res_metric_days"],
                msg: "Input should be less than or equal to 30",
                type: "less_than_equal",
              },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/retention/i));
    await user.type(screen.getByLabelText(/retention/i), "21");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(
      await screen.findByText(/input should be less than or equal to 30/i),
    ).toBeInTheDocument();
    // The rejection must not be the thing that disables Save.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();

    await user.clear(screen.getByLabelText(/retention/i));
    await user.type(screen.getByLabelText(/retention/i), "22");
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });
});
