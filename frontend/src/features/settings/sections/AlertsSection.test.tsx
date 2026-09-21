import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertsSection } from "@/features/settings/sections/AlertsSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    alert_radius_nm: 100,
    alerts: { enabled_templates: ["military"] },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AlertsSection", () => {
  it("renders prefilled radius and template selection", () => {
    installConfigApiMock();
    renderSection();

    expect(screen.getByLabelText(/alert radius/i)).toHaveValue("100");
    expect(
      screen.getByRole("checkbox", { name: /military aircraft/i }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /government aircraft/i }),
    ).not.toBeChecked();
  });

  it("blocks Save with an inline error for a zero alert radius", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/alert radius/i));
    await user.type(screen.getByLabelText(/alert radius/i), "0");

    expect(
      screen.getByText(/enter an alert radius greater than 0/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("allows blank (unlimited) and saves the toggled template list", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/alert radius/i));
    await user.click(
      screen.getByRole("checkbox", { name: /government aircraft/i }),
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      alert_radius_nm: null,
      alerts: { enabled_templates: ["military", "government"] },
    });
  });

  it("keeps Save enabled after a rejected save so the user can retry (R4-02)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ["alert_radius_nm"],
                msg: "Input should be greater than 0",
                type: "greater_than",
              },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/alert radius/i));
    await user.type(screen.getByLabelText(/alert radius/i), "5");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(
      await screen.findByText(/input should be greater than 0/i),
    ).toBeInTheDocument();
    // The rejection must not be the thing that disables Save.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();

    await user.clear(screen.getByLabelText(/alert radius/i));
    await user.type(screen.getByLabelText(/alert radius/i), "6");
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });
});
