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
});
