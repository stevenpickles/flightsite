import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OverheadButton } from "@/features/overhead/OverheadButton";
import { OverheadDialog } from "@/features/overhead/OverheadDialog";
import { useOverheadStore } from "@/features/overhead/useOverheadStore";
import type { ReceiverInfo } from "@/lib/api/live";
import type { OverheadPass, OverheadResponse } from "@/lib/api/overhead";
import { defaultReceiverInfo } from "@/test/aircraftApiMock";

function pass(overrides: Partial<OverheadPass> = {}): OverheadPass {
  return {
    sighting_id: 88213,
    icao: "ae1463",
    callsign: "RCH492",
    registration: "05-5140",
    aircraft_type: "C17",
    model: "C-17A",
    operator: "United States Air Force",
    open: false,
    fix_at: "2026-08-30T22:12:41.000Z",
    lat: 47.497,
    lon: -122.302,
    altitude_ft: 4200,
    distance_nm: 2.968,
    distance_kind: "slant",
    ground_distance_nm: 2.831,
    bearing_deg: 5.1,
    position_source: "adsb",
    ...overrides,
  };
}

function answer(overrides: Partial<OverheadResponse> = {}): OverheadResponse {
  return {
    at: "2026-08-30T22:10:00.000Z",
    window_minutes: 10,
    window_start: "2026-08-30T22:00:00.000Z",
    window_end: "2026-08-30T22:20:00.000Z",
    method: "closest_position_fix",
    receiver_configured: true,
    reason: null,
    candidates: 2,
    truncated: false,
    items: [
      pass(),
      pass({
        sighting_id: 88214,
        icao: "a1b2c3",
        callsign: null,
        registration: "N12345",
        distance_nm: 6.4,
        altitude_ft: null,
        distance_kind: "ground",
        open: true,
      }),
    ],
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Serves `/api/v1/receiver` and `/api/v1/overhead`; `overhead` may be a
 * function of the request URL, or a `[status, body]` pair for an error. */
function installMock(
  options: {
    receiver?: ReceiverInfo;
    overhead?: OverheadResponse | ((url: URL) => Response);
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/v1/receiver") {
      return jsonResponse(options.receiver ?? defaultReceiverInfo());
    }
    if (url.pathname === "/api/v1/overhead") {
      const overhead = options.overhead ?? answer();
      return typeof overhead === "function"
        ? overhead(url)
        : jsonResponse(overhead);
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function overheadRequests(fetchMock: ReturnType<typeof installMock>): URL[] {
  return fetchMock.mock.calls
    .map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname === "/api/v1/overhead");
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <OverheadButton placement="header" />
                <OverheadDialog />
              </>
            }
          />
          <Route path="/sightings/:id" element={<p>sighting page</p>} />
          <Route path="/aircraft/:icao" element={<p>aircraft page</p>} />
          <Route path="/settings" element={<p>settings page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openDialog() {
  const user = userEvent.setup();
  renderDialog();
  await user.click(screen.getByRole("button", { name: /What was that\?/ }));
  const dialog = await screen.findByRole("dialog", { name: "What was that?" });
  return { user, dialog };
}

afterEach(() => {
  act(() => {
    useOverheadStore.setState({ open: false });
  });
  vi.unstubAllGlobals();
});

describe("OverheadDialog", () => {
  it("asks about now, ±10 min, and ranks the closest fixes with links", async () => {
    const fetchMock = installMock();
    const { dialog } = await openDialog();

    const rows = await within(dialog).findAllByTestId("overhead-row");
    expect(rows).toHaveLength(2);

    const [request] = overheadRequests(fetchMock);
    expect(request?.searchParams.get("window")).toBe("10");
    expect(request?.searchParams.get("limit")).toBe("10");
    expect(request?.searchParams.has("at")).toBe(false);

    const first = within(rows[0]!);
    expect(first.getByText("RCH492")).toBeInTheDocument();
    expect(first.getByText("3.0 nm")).toBeInTheDocument();
    expect(first.getByText(/4,200 ft/)).toBeInTheDocument();
    expect(first.getByText("22:12:41")).toHaveAttribute(
      "dateTime",
      "2026-08-30T22:12:41.000Z",
    );
    expect(first.getByRole("link", { name: "Sighting" })).toHaveAttribute(
      "href",
      "/sightings/88213",
    );
    expect(first.getByRole("link", { name: "Aircraft" })).toHaveAttribute(
      "href",
      "/aircraft/ae1463",
    );

    const second = within(rows[1]!);
    expect(second.getByText("N12345")).toBeInTheDocument();
    expect(second.getByText(/altitude unknown/)).toBeInTheDocument();
    expect(second.getByText(/ground distance/)).toBeInTheDocument();
    expect(second.getByText(/sighting still open/)).toBeInTheDocument();

    expect(
      within(dialog).getByText(/closest position fix stored in the window/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/never interpolated/)).toBeInTheDocument();
    expect(within(dialog).getByTestId("timezone-note")).toHaveTextContent(
      "UTC",
    );
  });

  it("shows the answered moment in the picker, on the receiver's clock", async () => {
    installMock({
      receiver: defaultReceiverInfo({ timezone: "America/New_York" }),
    });
    const { dialog } = await openDialog();

    await waitFor(() =>
      expect(within(dialog).getByTestId("overhead-time")).toHaveValue(
        "2026-08-30T18:10",
      ),
    );
  });

  it("converts a picked receiver-local time to UTC for the request", async () => {
    const fetchMock = installMock({
      receiver: defaultReceiverInfo({ timezone: "America/New_York" }),
    });
    const { user, dialog } = await openDialog();
    await within(dialog).findAllByTestId("overhead-row");

    const input = within(dialog).getByTestId("overhead-time");
    await user.clear(input);
    await user.type(input, "2026-08-30T09:30");

    await waitFor(() =>
      expect(
        overheadRequests(fetchMock).some(
          (url) => url.searchParams.get("at") === "2026-08-30T13:30:00.000Z",
        ),
      ).toBe(true),
    );
  });

  it("asks again with the window chosen", async () => {
    const fetchMock = installMock();
    const { user, dialog } = await openDialog();
    await within(dialog).findAllByTestId("overhead-row");

    const thirty = within(dialog).getByRole("button", { name: "±30 min" });
    await user.click(thirty);

    expect(thirty).toHaveAttribute("aria-pressed", "true");
    await waitFor(() =>
      expect(
        overheadRequests(fetchMock).some(
          (url) => url.searchParams.get("window") === "30",
        ),
      ).toBe(true),
    );
  });

  it("formats distance and altitude in metric units when the receiver says so", async () => {
    installMock({ receiver: defaultReceiverInfo({ units: "metric" }) });
    const { dialog } = await openDialog();

    const [row] = await within(dialog).findAllByTestId("overhead-row");
    expect(within(row!).getByText("5.5 km")).toBeInTheDocument();
    expect(within(row!).getByText(/1,280 m/)).toBeInTheDocument();
  });

  it("says nothing passed when the window held no fixes", async () => {
    installMock({ overhead: answer({ items: [], candidates: 0 }) });
    const { dialog } = await openDialog();

    expect(
      await within(dialog).findByTestId("overhead-empty"),
    ).toHaveTextContent("Nothing passed within ±10 min of 22:10:00");
  });

  it("explains an unset receiver location and links to Settings", async () => {
    installMock({
      overhead: answer({
        items: [],
        candidates: 0,
        receiver_configured: false,
        reason: "receiver_location_unset",
      }),
    });
    const { dialog } = await openDialog();

    expect(
      await within(dialog).findByText(/No receiver location is set/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: "Set it in Settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("shows a retryable error state when the lookup fails", async () => {
    let fail = true;
    const fetchMock = installMock({
      overhead: () =>
        fail
          ? jsonResponse(
              { error: { code: "internal", message: "boom", detail: null } },
              500,
            )
          : jsonResponse(answer()),
    });
    const { user, dialog } = await openDialog();

    const error = await within(dialog).findByTestId("query-error-state");
    expect(error).toHaveTextContent("Could not look that up: boom");

    fail = false;
    await user.click(within(error).getByRole("button", { name: "Try again" }));

    expect(await within(dialog).findAllByTestId("overhead-row")).toHaveLength(
      2,
    );
    expect(overheadRequests(fetchMock).length).toBeGreaterThanOrEqual(2);
  });

  it("closes on Escape and on following a result link", async () => {
    installMock();
    const { user, dialog } = await openDialog();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /What was that\?/ }));
    const reopened = await screen.findByRole("dialog");
    const [row] = await within(reopened).findAllByTestId("overhead-row");
    await user.click(within(row!).getByRole("link", { name: "Sighting" }));

    expect(await screen.findByText("sighting page")).toBeInTheDocument();
    expect(useOverheadStore.getState().open).toBe(false);
    expect(dialog).not.toBeInTheDocument();
  });
});
