import { useEffect, useState } from "react";

/** Tailwind's default `md` breakpoint (768px) as a `max-width` query — the
 * sidebar's own breakpoint (R1-07/R2-08/R3-07/R4-06), matched exactly so
 * "below `md`" here means the same viewport range every `md:` utility class
 * elsewhere in the app already switches on. */
const MOBILE_QUERY = "(max-width: 767px)";

function matchesMobile(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return false;
  }
  return window.matchMedia(MOBILE_QUERY).matches;
}

/**
 * Tracks whether the viewport is currently below the `md` breakpoint, via
 * `matchMedia` rather than a `resize` listener — it fires once per
 * breakpoint crossing instead of on every pixel of a drag-resize, and
 * mirrors the same media query Tailwind's `md:` variant compiles to.
 *
 * Falls back to `false` (desktop) wherever `matchMedia` doesn't exist —
 * there is no SSR in this app, so in practice that only covers a test
 * environment that hasn't stubbed it, which is also the safe default: it
 * keeps every existing desktop-focused test's behaviour unchanged unless a
 * test opts in by mocking `matchMedia` (see `Sidebar.test.tsx`).
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(matchesMobile);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }
    const mql = window.matchMedia(MOBILE_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches);
    };
    mql.addEventListener("change", onChange);
    return () => {
      mql.removeEventListener("change", onChange);
    };
  }, []);

  return isMobile;
}
