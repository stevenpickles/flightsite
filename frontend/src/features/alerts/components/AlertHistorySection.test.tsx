import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AlertHistorySection,
  type AlertHistorySectionProps,
} from "@/features/alerts/components/AlertHistorySection";
import type { AlertMatch } from "@/lib/api/alertMatches";
import { alertMatch, installAlertsApiMock } from "@/test/alertsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The history links an airframe, so it needs a router as well as a query
 * client — the pairing `ActivityRow`'s own test uses. */
function renderHistory(props: AlertHistorySectionProps = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertHistorySection {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The section with the rule filter wired to real state, the way the Alerts
 * page owns it — so "clear" can be exercised end to end rather than only
 * asserting that a callback fired.
 */
function StatefulHistory({
  initial,
}: {
  initial: { id: number; name: string };
}) {
  const [ruleFilter, setRuleFilter] = useState<{
    id: number;
    name: string;
  } | null>(initial);
  return (
    <AlertHistorySection
      ruleFilter={ruleFilter}
      onClearRuleFilter={() => {
        setRuleFilter(null);
      }}
    />
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
    // Nothing is known about this airframe beyond its address, so the
    // address is what the link names — "Unknown" would name nothing.
    expect(within(row).getByRole("link", { name: "AE1463" })).toHaveAttribute(
      "href",
      "/aircraft/ae1463",
    );
  });

  it("names the aircraft the way a person would recognise it", async () => {
    // R4-08: the row used to read `Rule: Military aircraft | D25F97 |
    // Military aircraft` — the rule twice, and the aircraft as a bare hex.
    installAlertsApiMock({
      matches: [
        alertMatch({
          icao: "d25f97",
          callsign: "RCH492",
          aircraft_type: "C17",
          registration: "05-5153",
          reason: "Rule: Military aircraft",
          rule: { id: 1, name: "Military aircraft" },
        }),
      ],
    });

    renderHistory();

    const list = await screen.findByRole("list", { name: "Alert history" });
    const row = within(list).getByRole("listitem");
    expect(
      within(row).getByRole("link", { name: "RCH492 · C17 · 05-5153" }),
    ).toHaveAttribute("href", "/aircraft/d25f97");
    // The address stays reachable, once, beside the name it belongs to.
    expect(within(row).getByText("D25F97")).toBeInTheDocument();
  });

  it("names the rule once, not twice", async () => {
    installAlertsApiMock({
      matches: [
        alertMatch({
          reason: "Rule: Military aircraft",
          rule: { id: 1, name: "Military aircraft" },
        }),
      ],
    });

    renderHistory();

    const list = await screen.findByRole("list", { name: "Alert history" });
    const row = within(list).getByRole("listitem");
    // The stored reason *is* "Rule: " + the rule's name, so rendering the
    // name beside it said one thing twice.
    expect(within(row).queryByText("Military aircraft")).toBeNull();
    expect(
      within(row).getByText("Rule: Military aircraft"),
    ).toBeInTheDocument();
  });

  it("links the row to the sighting it happened during", async () => {
    installAlertsApiMock({ matches: [alertMatch({ sighting_id: 70 })] });

    renderHistory();

    const list = await screen.findByRole("list", { name: "Alert history" });
    expect(
      within(list).getByRole("link", { name: "Sighting 70" }),
    ).toHaveAttribute("href", "/sightings/70");
  });

  it("shows what was true of the sighting, and omits what was not known", async () => {
    installAlertsApiMock({
      matches: [
        alertMatch({
          id: 1,
          closest_approach_nm: 11.2,
          lowest_altitude_ft: 21000,
        }),
        alertMatch({ id: 2, reason: "Rule: Second" }),
      ],
    });

    renderHistory();

    const list = await screen.findByRole("list", { name: "Alert history" });
    const [withRecords, withoutRecords] = within(list).getAllByRole("listitem");
    expect(within(withRecords!).getByText("Closest 11.2 nm")).toBeVisible();
    expect(
      within(withRecords!).getByText("Lowest FL210 · 21,000 ft"),
    ).toBeVisible();
    // A sighting that never had a position publishes null for both, and
    // §2.7's absence is rendered as absence rather than as a zero.
    expect(within(withoutRecords!).queryByText(/^Closest/)).toBeNull();
    expect(within(withoutRecords!).queryByText(/^Lowest/)).toBeNull();
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

  it("heads the history with the rule it is narrowed to", async () => {
    installAlertsApiMock({ matches: [alertMatch()] });

    renderHistory({ ruleFilter: { id: 1, name: "Military aircraft" } });

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Alert history: Military aircraft",
      }),
    ).toBeInTheDocument();
  });

  it("carries no heading while it is showing every rule", async () => {
    // Unfiltered, the History tab already says what this is — the heading is
    // the announcement that the view has been narrowed, so it appears with
    // the filter rather than sitting there restating the tab.
    installAlertsApiMock({ matches: [alertMatch()] });

    renderHistory();

    await screen.findByRole("list", { name: "Alert history" });
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("asks the endpoint for one rule's matches", async () => {
    // Server-side, not a filter of the page already on screen: the rule the
    // user asked about may not have fired inside the newest 25 matches.
    const { fetchMock } = installAlertsApiMock({
      matches: [
        alertMatch({
          id: 1,
          reason: "Rule: Military",
          rule: { id: 1, name: "Military" },
        }),
        alertMatch({
          id: 2,
          reason: "Rule: Rare type",
          rule: { id: 2, name: "Rare type" },
        }),
      ],
    });

    renderHistory({ ruleFilter: { id: 2, name: "Rare type" } });

    expect(await screen.findByText("Rule: Rare type")).toBeInTheDocument();
    expect(screen.queryByText("Rule: Military")).toBeNull();

    const requested = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.startsWith("/api/v1/alerts/matches"));
    expect(requested).not.toHaveLength(0);
    for (const url of requested) {
      expect(new URLSearchParams(url.split("?")[1]).get("rule_id")).toBe("2");
    }
  });

  it("shows an empty history for a rule that has caught nothing", async () => {
    // Includes the id of a rule that no longer exists: the endpoint answers
    // an unknown id with an empty page rather than an error, and deleting a
    // rule really does delete its matches.
    installAlertsApiMock({
      matches: [alertMatch({ rule: { id: 1, name: "Military" } })],
    });

    renderHistory({ ruleFilter: { id: 99, name: "Deleted rule" } });

    expect(
      await screen.findByText("“Deleted rule” has not fired yet."),
    ).toBeInTheDocument();
  });

  it("clears back to every rule", async () => {
    const user = userEvent.setup();
    installAlertsApiMock({
      matches: [
        alertMatch({
          id: 1,
          reason: "Rule: Military",
          rule: { id: 1, name: "Military" },
        }),
        alertMatch({
          id: 2,
          reason: "Rule: Rare type",
          rule: { id: 2, name: "Rare type" },
        }),
      ],
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <StatefulHistory initial={{ id: 2, name: "Rare type" }} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText("Rule: Rare type");
    expect(screen.queryByText("Rule: Military")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Show all rules" }));

    expect(await screen.findByText("Rule: Military")).toBeInTheDocument();
    // The heading and the control both go with the filter they described.
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show all rules" })).toBeNull();
  });

  it("offers no clear control when the caller has no filter to clear", async () => {
    installAlertsApiMock({ matches: [alertMatch()] });

    renderHistory();

    await screen.findByRole("list", { name: "Alert history" });
    expect(screen.queryByRole("button", { name: "Show all rules" })).toBeNull();
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
