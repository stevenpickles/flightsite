import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useFilterUrlSync } from "@/features/filters/hooks/useFilterUrlSync";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";

function TestHost() {
  useFilterUrlSync();
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
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
});

describe("useFilterUrlSync", () => {
  it("seeds the store from the URL on mount", () => {
    renderHost("/?hide_stale=1&dist=100");
    expect(useFilterStore.getState().filters).toMatchObject({
      hideStale: true,
      maxDistanceNm: 100,
    });
  });

  it("leaves the store at the defaults for a bare URL", () => {
    renderHost("/");
    expect(useFilterStore.getState().filters).toEqual(DEFAULT_FILTERS);
  });

  it("never overwrites a seeded URL with the defaults on the seeding render", () => {
    renderHost("/?hide_stale=1");
    // If the write-effect fired with the pre-seed (default) filters before
    // the seed took effect, `hide_stale` would have been briefly stripped.
    // Asserting it directly after mount rules that out.
    expect(screen.getByTestId("query").textContent).toContain("hide_stale=1");
  });

  it("writes a filter change into the URL", async () => {
    renderHost("/");
    await act(async () => {
      useFilterStore.getState().setHideStale(true);
    });
    expect(screen.getByTestId("query").textContent).toContain("hide_stale=1");
  });

  it("clears the URL when filters return to the defaults", async () => {
    renderHost("/?hide_stale=1");
    await act(async () => {
      useFilterStore.getState().clearAll();
    });
    expect(screen.getByTestId("query").textContent).toBe("");
  });

  it("preserves an unrelated query param", async () => {
    renderHost("/?tab=map");
    await act(async () => {
      useFilterStore.getState().setHideStale(true);
    });
    const query = screen.getByTestId("query").textContent ?? "";
    expect(query).toContain("tab=map");
    expect(query).toContain("hide_stale=1");
  });
});
