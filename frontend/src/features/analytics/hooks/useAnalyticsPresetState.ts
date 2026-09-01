/**
 * The Analytics page's preset state, backed directly by the URL (roadmap
 * slice 032: "preset selector... URL-persisted"). Mirrors
 * `features/aircraft-page/hooks/useAircraftTableState.ts` — the URL *is*
 * the state, read fresh on every render and written with `replace` so
 * switching presets never grows the browser history stack.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import type { AnalyticsPreset } from "@/lib/api/analytics";

import {
  parseAnalyticsPreset,
  serializeAnalyticsPreset,
} from "@/features/analytics/lib/urlState";

export interface UseAnalyticsPresetStateResult {
  preset: AnalyticsPreset;
  setPreset: (preset: AnalyticsPreset) => void;
}

export function useAnalyticsPresetState(): UseAnalyticsPresetStateResult {
  const [searchParams, setSearchParams] = useSearchParams();

  const preset = useMemo(
    () => parseAnalyticsPreset(searchParams),
    [searchParams],
  );

  const setPreset = useCallback(
    (next: AnalyticsPreset) => {
      setSearchParams(serializeAnalyticsPreset(next), { replace: true });
    },
    [setSearchParams],
  );

  return { preset, setPreset };
}
