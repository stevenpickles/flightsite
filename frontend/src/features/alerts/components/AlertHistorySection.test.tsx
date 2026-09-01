import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertHistorySection } from "@/features/alerts/components/AlertHistorySection";
import type { AlertMatch } from "@/lib/api/alertMatches";
import { alertMatch, installAlertsApiMock } from "@/test/alertsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The history links an airframe, so it needs a router as well as a query
 * client — the pairing `ActivityRow`'s own test uses. */
function renderHistory() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertHistorySection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 26 matches — one more than a page — newest first. */
function manyMatches(): AlertMatch[] {
  return Array.from({ length: 26 }, (_entry, index) =>
    alertMatch({ id: 100 - index, reason: `Rule: Number ${index}` }),
  );
}

describe("AlertHistorySection", () => {
  it("says so when nothing has fired", async () => {
    installAlertsApiMock();

    renderHistory();

    expect(
      await screen.findByText("No alerts have fired yet."),
    ).toBeInTheDocument();
  });

  it("shows a match with the reason recorded at the time", async () => {
    installAlertsApiMock({
      matches: [
        alertMatch({ reason: "Rule: Military aircraft", severity: "high" }),
      ],
    });

    renderHistory();

    const list = await screen.findByRole("list", { name: "Alert history" });
    const row = within(list).getByRole("listitem");
    // The stored reason, never one recomposed from the rule as it stands
    // now: the history says what the user was actually shown.
    expect(
      within(row).getByText("Rule: Military aircraft"),
    ).toBeInTheDocument();
    expect(within(row).getByText("High")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "AE1463" })).toHaveAttribute(
      "href",
      "/aircraft/ae1463",
    );
  });

  it("names the built-in detector behind a match that has no rule", async () => {
    installAlertsApiMock({
      matches: [
        alertMatch({
          severity: "critical",
          reason: "Emergency squawk 7700",
          rule: null,
          builtin_key: "emergency_7700",
        }),
      ],
    });

    renderHistory();

    // SPEC §47's emergency detections fire without a rule, so the row names
    // the detector instead of leaving the source blank.
    expect(
      await screen.findByText("Squawk 7700 — general emergency"),
    ).toBeInTheDocument();
  });

  it("filters to one severity", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      matches: [
        alertMatch({ id: 1, severity: "high", reason: "Rule: Military" }),
        alertMatch({ id: 2, severity: "info", reason: "Rule: First ever" }),
      ],
    });

    renderHistory();
    await screen.findByText("Rule: Military");

    await user.selectOptions(screen.getByLabelText("Severity"), "info");

    expect(await screen.findByText("Rule: First ever")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Rule: Military")).toBeNull();
    });
  });

  it("pages older and back again", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({ matches: manyMatches() });

    renderHistory();
    await screen.findByText("Rule: Number 0");

    // "Newer" has nowhere to go from the first page.
    expect(screen.getByRole("button", { name: "Newer" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Older" }));

    expect(await screen.findByText("Rule: Number 25")).toBeInTheDocument();
    // A page that comes back short of the page size is the end — the
    // endpoint reports no total, so this is the only signal there is.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Older" })).toBeDisabled();
    });

    await user.click(screen.getByRole("button", { name: "Newer" }));

    expect(await screen.findByText("Rule: Number 0")).toBeInTheDocument();
  });

  it("reports a failure to load the history", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: { code: "boom", message: "no history" } }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );

    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load the alert history/i,
    );
  });
});
