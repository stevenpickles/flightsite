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

  it("drills into one rule's matches from its card", async () => {
    // Issue #98: "show me what this rule has caught" crosses two areas of the
    // page — the affordance is on a rule card, the answer is in the history —
    // which is why the page owns the filter rather than either section.
    const user = userEvent.setup();
    installAlertsApiMock({
      rules: [
        alertRule({ id: 1, name: "Military aircraft" }),
        alertRule({ id: 2, name: "Rare types" }),
      ],
      matches: [
        alertMatch({
          id: 1,
          reason: "Rule: Military aircraft",
          rule: { id: 1, name: "Military aircraft" },
        }),
        alertMatch({
          id: 2,
          reason: "Rule: Rare types",
          rule: { id: 2, name: "Rare types" },
        }),
      ],
    });

    renderPage();

    await user.click(screen.getByRole("tab", { name: "Rules" }));
    await user.click(
      await screen.findByRole("button", {
        name: "Show matches for Rare types",
      }),
    );

    // The History tab is now the selected one, narrowed to that rule and
    // saying so.
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Alert history: Rare types",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Rule: Rare types")).toBeInTheDocument();
    expect(screen.queryByText("Rule: Military aircraft")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Show all rules" }));

    expect(
      await screen.findByText("Rule: Military aircraft"),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
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
