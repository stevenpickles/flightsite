import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useSearchParams } from "react-router-dom";
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

/** A sibling of `AlertsPage` reading the same router's search params, so a
 * test can assert on what the page wrote to the URL. */
function SearchParamsProbe() {
  const [searchParams] = useSearchParams();
  return <div data-testid="url-query">{searchParams.toString()}</div>;
}

function renderPageAt(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AlertsPage />
        <SearchParamsProbe />
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

describe("AlertsPage URL state (R4-07)", () => {
  it("puts the selected tab into ?tab= and reads it back", async () => {
    const user = userEvent.setup();
    installAlertsApiMock();

    renderPageAt("/alerts");
    await user.click(screen.getByRole("tab", { name: "Templates" }));

    expect(screen.getByTestId("url-query").textContent).toBe("tab=templates");
    expect(screen.getByRole("tab", { name: "Templates" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("deep-links to a tab from ?tab=", async () => {
    installAlertsApiMock({
      matches: [alertMatch({ reason: "Rule: Military aircraft" })],
    });

    renderPageAt("/alerts?tab=history");

    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      await screen.findByText("Rule: Military aircraft"),
    ).toBeInTheDocument();
  });

  it("deep-links to a filtered rule's history from ?rule_id= alone", async () => {
    // Evidence from the review: visiting ?rule_id=1 with no ?tab= left the
    // page on Watchlists, showing a filter nothing on screen explained.
    installAlertsApiMock({
      rules: [alertRule({ id: 3, name: "Rare types" })],
      matches: [
        alertMatch({
          reason: "Rule: Rare types",
          rule: { id: 3, name: "Rare types" },
        }),
      ],
    });

    renderPageAt("/alerts?rule_id=3");

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
  });

  it("writes tab=history and rule_id= when drilling into a rule's matches", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      rules: [alertRule({ id: 7, name: "Rare types" })],
    });

    renderPageAt("/alerts");
    await user.click(screen.getByRole("tab", { name: "Rules" }));
    await user.click(
      await screen.findByRole("button", {
        name: "Show matches for Rare types",
      }),
    );

    expect(screen.getByTestId("url-query").textContent).toBe(
      "tab=history&rule_id=7",
    );
  });

  it("clears rule_id from the URL without leaving the History tab", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      rules: [alertRule({ id: 7, name: "Rare types" })],
    });

    renderPageAt("/alerts?tab=history&rule_id=7");
    await screen.findByRole("heading", {
      level: 2,
      name: "Alert history: Rare types",
    });

    await user.click(screen.getByRole("button", { name: "Show all rules" }));

    expect(screen.getByTestId("url-query").textContent).toBe("tab=history");
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("survives a refresh: re-rendering at the same URL restores the view", async () => {
    installAlertsApiMock({
      rules: [alertRule({ id: 3, name: "Rare types" })],
    });

    const { unmount } = renderPageAt("/alerts?tab=rules");
    expect(screen.getByRole("tab", { name: "Rules" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    unmount();

    // A fresh mount at the same URL is what a browser refresh amounts to.
    renderPageAt("/alerts?tab=rules");
    expect(screen.getByRole("tab", { name: "Rules" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
