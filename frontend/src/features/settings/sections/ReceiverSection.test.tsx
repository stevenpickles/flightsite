import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReceiverSection } from "@/features/settings/sections/ReceiverSection";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const config = defaultFlightSiteConfig({
    location: {
      latitude: 47.6,
      longitude: -122.3,
      site_name: "Home Roof",
      antenna_height_ft: 30,
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReceiverSection config={config} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReceiverSection", () => {
  it("renders prefilled from the current config, with Save disabled until edited", () => {
    installConfigApiMock();
    renderSection();

    expect(screen.getByLabelText(/site name/i)).toHaveValue("Home Roof");
    expect(screen.getByLabelText(/latitude/i)).toHaveValue("47.6");
    expect(screen.getByLabelText(/longitude/i)).toHaveValue("-122.3");
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("shows the restart-required badge", () => {
    installConfigApiMock();
    renderSection();
    expect(screen.getByText(/applies on next restart/i)).toBeInTheDocument();
  });

  it("marks the section dirty after an edit and enables Save", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/site name/i));
    await user.type(screen.getByLabelText(/site name/i), "New Name");

    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });

  it("blocks Save with an inline error for an out-of-range latitude", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/latitude/i));
    await user.type(screen.getByLabelText(/latitude/i), "95");

    expect(
      screen.getByText(/enter a latitude between -90 and 90/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("saves the edited location, sends the expected payload, and clears the dirty state", async () => {
    const { fetchMock } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/site name/i));
    await user.type(screen.getByLabelText(/site name/i), "Updated Site");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls).toHaveLength(1);
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as Record<string, unknown>;
    expect(body).toEqual({
      location: {
        site_name: "Updated Site",
        latitude: 47.6,
        longitude: -122.3,
        antenna_height_ft: 30,
      },
    });
  });

  it("renders a server-side validation error inline next to its field", async () => {
    installConfigApiMock();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ["location", "latitude"],
                msg: "Input should be less than or equal to 90",
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

    await user.type(screen.getByLabelText(/site name/i), " Edited");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(
      await screen.findByText(/input should be less than or equal to 90/i),
    ).toBeInTheDocument();
  });
});
