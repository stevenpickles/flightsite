import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useCurrentUrl } from "./useCurrentUrl";

describe("useCurrentUrl", () => {
  it("combines the window origin with the router's path and query string", () => {
    const { result } = renderHook(() => useCurrentUrl(), {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={["/aircraft/ae1463?tab=history"]}>
          {children}
        </MemoryRouter>
      ),
    });

    expect(result.current).toBe(
      `${window.location.origin}/aircraft/ae1463?tab=history`,
    );
  });

  it("has no query string when the route carries none", () => {
    const { result } = renderHook(() => useCurrentUrl(), {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={["/sightings/42"]}>
          {children}
        </MemoryRouter>
      ),
    });

    expect(result.current).toBe(`${window.location.origin}/sightings/42`);
  });
});
