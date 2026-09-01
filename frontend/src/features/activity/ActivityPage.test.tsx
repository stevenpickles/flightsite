import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PAGE_SIZE } from "@/features/activity/lib/urlState";
import {
  activityEvent,
  activityList,
  installActivityApiMock,
} from "@/test/activityApiMock";
import { renderApp } from "@/test/test-utils";

/** Every `/api/v1/activity` URL the mock was asked for, in order. */
function activityRequests(
  fetchMock: ReturnType<typeof installActivityApiMock>["fetchMock"],
): URL[] {
  return fetchMock.mock.calls
    .map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname === "/api/v1/activity");
}

function page(events: number, from = 0) {
  return activityList(
    Array.from({ length: events }, (_, index) =>
      activityEvent({
        id: from + index + 1,
        // Descending, like the endpoint's own ordering, so the rendered order
        // is the one a real page would have.
        at: new Date(Date.UTC(2026, 7, 31, 12, 0, from + events - index))
          .toISOString()
          .replace("Z", "Z"),
      }),
    ),
    { limit: PAGE_SIZE },
  );
}

describe("ActivityPage", () => {
  it("renders the feed under its own heading, outside the seven nav sections", async () => {
    // SPEC §10 fixes the sidebar at seven, so this route builds its own
    // heading instead of reading one from NAV_ITEMS.
    installActivityApiMock({ list: page(3) });
    renderApp("/activity");

    expect(
      screen.getByRole("heading", { level: 1, name: "Activity" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(3),
    );
    expect(
      screen.queryByRole("link", { name: "Activity" }),
    ).not.toBeInTheDocument();
  });

  it("sends one repeated type parameter per selected chip", async () => {
    const { fetchMock } = installActivityApiMock({ list: page(2) });
    const user = userEvent.setup();
    renderApp("/activity");
    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(2),
    );

    const filter = screen.getByRole("group", { name: /filter by event type/i });
    await user.click(within(filter).getByRole("button", { name: "New types" }));
    await user.click(
      within(filter).getByRole("button", { name: "Milestones" }),
    );

    await waitFor(() => {
      const last = activityRequests(fetchMock).at(-1);
      expect(last?.searchParams.getAll("type")).toEqual([
        "new_type",
        "milestone",
      ]);
    });
    // Repeated `type=`, never a comma-joined string — a value stays a value.
    expect(
      within(filter).getByRole("button", { name: "New types" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("clears every filter from the URL and the request", async () => {
    const { fetchMock } = installActivityApiMock({ list: page(1) });
    const user = userEvent.setup();
    const { router } = renderApp("/activity?type=new_type&type=milestone");
    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(1),
    );

    await user.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() => {
      const last = activityRequests(fetchMock).at(-1);
      expect(last?.searchParams.getAll("type")).toEqual([]);
    });
    expect(router.state.location.search).toBe("");
  });

  it("pages forward while a full page comes back, and back again", async () => {
    // `total` is always null on this endpoint (§2.4), so "a full page came
    // back" is the only signal there is a next one.
    const { fetchMock } = installActivityApiMock({
      list: (url) =>
        url.searchParams.get("offset") === "0" ? page(PAGE_SIZE) : page(4, 100),
    });
    const user = userEvent.setup();
    renderApp("/activity");
    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(PAGE_SIZE),
    );

    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(screen.getAllByTestId("activity-row")).toHaveLength(4),
    );
    expect(activityRequests(fetchMock).at(-1)?.searchParams.get("offset")).toBe(
      String(PAGE_SIZE),
    );
    // A short page is the end of the feed: forward is now disabled.
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() =>
      expect(
        activityRequests(fetchMock).at(-1)?.searchParams.get("offset"),
      ).toBe("0"),
    );
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("distinguishes an empty feed from an empty filter result", async () => {
    installActivityApiMock({ list: activityList([]) });
    const user = userEvent.setup();
    renderApp("/activity");

    await waitFor(() =>
      expect(screen.getByText("Nothing has happened yet.")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "New types" }));
    await waitFor(() =>
      expect(
        screen.getByText("No activity matches these filters."),
      ).toBeInTheDocument(),
    );
  });

  it("reports a failed request instead of an empty feed", async () => {
    installActivityApiMock({ listStatus: 500 });
    renderApp("/activity");

    await waitFor(() =>
      expect(
        screen.getByText(/could not load the activity feed/i),
      ).toBeInTheDocument(),
    );
  });
});
