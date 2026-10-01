import { vi } from "vitest";

/**
 * A scripted `window.matchMedia` stand-in for rendering below the `md`
 * breakpoint — jsdom answers `matches: false` for every query regardless of
 * `window.innerWidth`, so a phone render has to be driven this way
 * (`useIsMobile`'s own doc comment). The same shape `Sidebar.test.tsx`
 * builds inline, shared here for the phone Live Map tests (roadmap slice
 * 084). `dispatch` simulates the browser firing `change` on an existing
 * `MediaQueryList` — a rotation or resize crossing the breakpoint.
 *
 * Pair with `vi.unstubAllGlobals()` in `afterEach`.
 */
export function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  let matches = initialMatches;
  const mediaQueryList = {
    get matches() {
      return matches;
    },
    media: "(max-width: 767px)",
    addEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.add(listener);
    },
    removeEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.delete(listener);
    },
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue(mediaQueryList as unknown as MediaQueryList),
  );
  return {
    dispatch(next: boolean) {
      matches = next;
      for (const listener of listeners) {
        listener({ matches: next } as MediaQueryListEvent);
      }
    },
  };
}
