import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertsPage } from "@/pages/AlertsPage";
import {
  alertMatch,
  alertRule,
  installAlertsApiMock,
} from "@/test/alertsApiMock";
import { watchlist } from "@/test/watchlistsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The History tab links an airframe, so the page needs a router as well as
 * a query client. */
function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AlertsPage", () => {
  it("renders the page heading and opens on the Watchlists area", async () => {
    installAlertsApiMock({
      watchlists: [watchlist({ name: "Police Helicopters" })],
    });

    renderPage();

    expect(
      screen.getByRole("heading", { level: 1, name: "Alerts" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Police Helicopters")).toBeInTheDocument();
  });

  it("offers every area of the page as a tab", () => {
    installAlertsApiMock();

    renderPage();

    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Watchlists",
      "Rules",
      "Templates",
      "History",
    ]);
  });

  it("switches to the rule builder's area", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({ rules: [alertRule({ name: "Military aircraft" })] });

    renderPage();

    await user.click(screen.getByRole("tab", { name: "Rules" }));

    expect(
      await screen.findByRole("article", { name: "Military aircraft" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Rules" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches to the template gallery", async () => {
    const user = userEvent.setup();
    installAlertsApiMock();

    renderPage();

    await user.click(screen.getByRole("tab", { name: "Templates" }));

    expect(
      await screen.findByRole("article", { name: "Emergency squawk" }),
    ).toBeInTheDocument();
  });

  it("switches to the alert history", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      matches: [alertMatch({ reason: "Rule: Military aircraft" })],
    });

    renderPage();

    await user.click(screen.getByRole("tab", { name: "History" }));

    expect(
      await screen.findByText("Rule: Military aircraft"),
    ).toBeInTheDocument();
  });
});
