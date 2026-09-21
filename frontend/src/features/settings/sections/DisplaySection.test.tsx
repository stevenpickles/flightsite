import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DisplaySection } from "@/features/settings/sections/DisplaySection";
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
      <DisplaySection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DisplaySection", () => {
  it("renders prefilled from the current config", () => {
    installConfigApiMock();
    renderSection();

    expect(screen.getByLabelText(/display radius/i)).toHaveValue("250");
    expect(screen.getByLabelText(/range ring radii/i)).toHaveValue(
      "50, 100, 150, 200",
    );
    expect(
      screen.getByRole("checkbox", { name: /show range rings/i }),
    ).toBeChecked();
  });

  it("blocks Save for an invalid range-ring list", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/range ring radii/i));
    await user.type(screen.getByLabelText(/range ring radii/i), "50, 50");

    expect(
      screen.getByText(/range ring radii must be unique/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("saves the edited display radius, basemap, and range rings", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/display radius/i));
    await user.type(screen.getByLabelText(/display radius/i), "300");
    await user.selectOptions(
      screen.getByLabelText(/default basemap/i),
      "light-aviation",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      display_radius_nm: 300,
      map: {
        basemap: "light-aviation",
        range_rings_enabled: true,
        range_ring_radii_nm: [50, 100, 150, 200],
      },
    });
  });

  it("keeps Save enabled after a rejected save so the user can retry (R4-02)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = (init?.method ?? "GET").toUpperCase();
        if (url === "/api/internal/config" && method === "GET") {
          return new Response(
            JSON.stringify({
              first_run: false,
              config: defaultFlightSiteConfig(),
              secrets_set: { "enrichment.aerodatabox_api_key": false },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url === "/api/internal/config" && method === "PUT") {
          return new Response(
            JSON.stringify({
              detail: [
                {
                  loc: ["display_radius_nm"],
                  msg: "Input should be greater than 0",
                  type: "greater_than",
                },
              ],
            }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          );
        }
        throw new Error(`Unhandled fetch in test: ${method} ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/display radius/i));
    await user.type(screen.getByLabelText(/display radius/i), "300");
    const saveButton = screen.getByRole("button", { name: /^save$/i });
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    expect(
      await screen.findByText(/input should be greater than 0/i),
    ).toBeInTheDocument();
    // The server's rejection must not be the thing that disables Save —
    // that would leave the section unsavable until a page reload.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();

    await user.type(screen.getByLabelText(/display radius/i), "1");
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });
});
