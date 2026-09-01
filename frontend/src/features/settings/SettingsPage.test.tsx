import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { installConfigApiMock } from "@/test/configApiMock";

function renderSettingsPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/setup" element={<div>Setup wizard page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsPage", () => {
  it("shows a loading state, then every section, once the config loads", async () => {
    installConfigApiMock();
    renderSettingsPage();

    expect(screen.getByText(/loading configuration/i)).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { name: "Receiver", level: 2 }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Settings", level: 1 }),
    ).toBeInTheDocument();

    for (const heading of [
      "Decoder",
      "Decoder",
      "Units & time",
      "Display",
      "Alerts",
      "Notifications",
      "Enrichment",
      "Aircraft Metadata",
      "Retention",
    ]) {
      expect(
        screen.getByRole("heading", { name: heading, level: 2 }),
      ).toBeInTheDocument();
    }
  });

  it("shows a retry affordance when the initial config load fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );
    const user = userEvent.setup();
    renderSettingsPage();

    expect(
      await screen.findByText(/could not load the current configuration/i),
    ).toBeInTheDocument();

    const { fetchMock } = installConfigApiMock();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(fetchMock).toHaveBeenCalled();
    expect(
      await screen.findByRole("heading", { name: "Receiver", level: 2 }),
    ).toBeInTheDocument();
  });

  it("links to the setup wizard", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSettingsPage();

    const link = await screen.findByRole("link", {
      name: /re-run setup wizard/i,
    });
    expect(link).toHaveAttribute("href", "/setup");

    await user.click(link);
    expect(await screen.findByText("Setup wizard page")).toBeInTheDocument();
  });
});
