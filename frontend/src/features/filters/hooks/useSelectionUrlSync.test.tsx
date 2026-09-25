import { act, render, screen } from "@testing-library/react";
import {
  createMemoryRouter,
  MemoryRouter,
  RouterProvider,
  useSearchParams,
} from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useSelectionUrlSync } from "@/features/filters/hooks/useSelectionUrlSync";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

function TestHost() {
  useSelectionUrlSync();
  const [searchParams] = useSearchParams();
  return <div data-testid="query">{searchParams.toString()}</div>;
}

function renderHost(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <TestHost />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

describe("useSelectionUrlSync", () => {
  it("selects the aircraft named in the URL on mount", () => {
    renderHost("/?selected=aaaaaa");
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
  });

  it("keeps the selection when the aircraft is not (yet) in the live set", () => {
    // The store holds the intent even with no matching record — the panel's
    // own "no live data" rendering is what covers the rest (R1-09).
    renderHost("/?selected=zzzzzz");
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("zzzzzz");
    expect(useLiveAircraftStore.getState().aircraft.zzzzzz).toBeUndefined();
  });

  it("leaves the selection at null for a bare URL", () => {
    renderHost("/");
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
  });

  it("never overwrites a seeded URL selection on the seeding render", () => {
    renderHost("/?selected=aaaaaa");
    // If the write-effect fired with the pre-seed (null) selection before
    // the seed took effect, `selected` would have been briefly stripped.
    expect(screen.getByTestId("query").textContent).toContain(
      "selected=aaaaaa",
    );
  });

  it("writes a selection change into the URL", async () => {
    renderHost("/");
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("bbbbbb");
    });
    expect(screen.getByTestId("query").textContent).toContain(
      "selected=bbbbbb",
    );
  });

  it("clears the URL when the selection is cleared", async () => {
    renderHost("/?selected=aaaaaa");
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft(null);
    });
    expect(screen.getByTestId("query").textContent).toBe("");
  });

  it("replaces rather than pushes on every re-selection", async () => {
    renderHost("/");
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("bbbbbb");
    });
    // Two selections in a row leave exactly one query string behind, the
    // latest — a `push` would still show this (the current entry is always
    // the newest either way); the Back-button half of "replace, not push"
    // is exercised end-to-end on `LiveMapPage` in `LiveMapPage.test.tsx`.
    expect(screen.getByTestId("query").textContent).toBe("selected=bbbbbb");
  });

  it("preserves an unrelated query param", async () => {
    renderHost("/?tab=map");
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    const query = screen.getByTestId("query").textContent ?? "";
    expect(query).toContain("tab=map");
    expect(query).toContain("selected=aaaaaa");
  });

  it("lets Back skip over every re-selection in one step (replace, not push)", async () => {
    // Two entries so there is somewhere for Back to land: a prior page
    // (`/other`, standing in for wherever the user was before), then the
    // filtered map this test's selections happen on.
    const router = createMemoryRouter(
      [
        { path: "/", element: <TestHost /> },
        { path: "/other", element: <div>elsewhere</div> },
      ],
      { initialEntries: ["/other", "/?hide_stale=1"], initialIndex: 1 },
    );
    render(<RouterProvider router={router} />);

    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    await act(async () => {
      useLiveAircraftStore.getState().selectAircraft("bbbbbb");
    });
    expect(router.state.location.search).toBe("?hide_stale=1&selected=bbbbbb");

    await act(async () => {
      router.navigate(-1);
    });
    // Both selections replaced the one entry already on the stack — from
    // the router's point of view neither added an entry of its own — so a
    // single Back leaves the map entirely, landing on `/other`, rather than
    // stepping back through "aaaaaa" first.
    expect(router.state.location.pathname).toBe("/other");
  });

  it("writes an already-selected aircraft's icao into the URL on mount", () => {
    // The scenario `features/notifications/lib/dispatch.ts` produces: a
    // notification click selects the aircraft directly, via
    // `useLiveAircraftStore.getState().selectAircraft`, before the Live Map
    // (and this hook) ever mounts.
    useLiveAircraftStore.getState().selectAircraft("cccccc");
    renderHost("/");
    expect(screen.getByTestId("query").textContent).toBe("selected=cccccc");
  });
});
