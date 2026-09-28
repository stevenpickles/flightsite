import { useLocation } from "react-router-dom";

/**
 * The full, absolute URL of the current view (roadmap slice 082) — origin
 * plus the router's own path and query string, so it matches exactly what
 * `useSelectionUrlSync` and `useFilterUrlSync` have already written to the
 * address bar. `ShareControls`' three actions (Copy link, `navigator.share`,
 * the QR popover) all read this on click rather than holding it in state, so
 * a filter edit or a `?selected=` change between renders costs nothing.
 */
export function useCurrentUrl(): string {
  const location = useLocation();
  return `${window.location.origin}${location.pathname}${location.search}`;
}
