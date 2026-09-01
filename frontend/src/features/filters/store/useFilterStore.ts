/**
 * The live filter set as UI state (roadmap slice 017).
 *
 * A separate store from `useLiveAircraftStore` on purpose: filters are a
 * user preference about *what to look at*, not part of the live picture
 * itself, and keeping them apart means the frame loop
 * (`features/map/aircraft/frame.ts`) can read both independently through
 * `getState()` without either store's updates forcing the other to
 * recompute anything it does not need to. Every setter replaces the whole
 * `filters` object (never mutates in place) so `filteredLiveAircraftCache`'s
 * reference-equality memo can tell "unchanged" from "edited" for free.
 */

import { create } from "zustand";

import {
  DEFAULT_FILTERS,
  type ClassificationFlag,
  type GroundTrafficMode,
  type LiveFilters,
} from "@/features/filters/types";

export interface FilterState {
  filters: LiveFilters;
  setAltitudeRange: (minFt: number | null, maxFt: number | null) => void;
  setMaxDistanceNm: (nm: number | null) => void;
  setCategoryText: (text: string) => void;
  setOperatorText: (text: string) => void;
  setOperatorGroupText: (text: string) => void;
  toggleClassification: (flag: ClassificationFlag) => void;
  toggleMissionCategory: (mission: string) => void;
  setInterestingOnly: (value: boolean) => void;
  setEmergencyOnly: (value: boolean) => void;
  setHideNonPositioned: (value: boolean) => void;
  setGroundTraffic: (mode: GroundTrafficMode) => void;
  setHideStale: (value: boolean) => void;
  setLiveSetQuery: (query: string) => void;
  /** Wholesale replacement — used to restore filters parsed from the URL
   * on load (`hooks/useFilterUrlSync.ts`). */
  replaceFilters: (filters: LiveFilters) => void;
  clearAll: () => void;
}

function toggleMember<T>(list: readonly T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((entry) => entry !== value)
    : [...list, value];
}

export const useFilterStore = create<FilterState>((set) => ({
  filters: DEFAULT_FILTERS,

  setAltitudeRange: (minFt, maxFt) => {
    set((state) => ({
      filters: { ...state.filters, altitudeMinFt: minFt, altitudeMaxFt: maxFt },
    }));
  },
  setMaxDistanceNm: (nm) => {
    set((state) => ({ filters: { ...state.filters, maxDistanceNm: nm } }));
  },
  setCategoryText: (text) => {
    set((state) => ({ filters: { ...state.filters, categoryText: text } }));
  },
  setOperatorText: (text) => {
    set((state) => ({ filters: { ...state.filters, operatorText: text } }));
  },
  setOperatorGroupText: (text) => {
    set((state) => ({
      filters: { ...state.filters, operatorGroupText: text },
    }));
  },
  toggleClassification: (flag) => {
    set((state) => ({
      filters: {
        ...state.filters,
        classifications: toggleMember(state.filters.classifications, flag),
      },
    }));
  },
  toggleMissionCategory: (mission) => {
    set((state) => ({
      filters: {
        ...state.filters,
        missionCategories: toggleMember(
          state.filters.missionCategories,
          mission,
        ),
      },
    }));
  },
  setInterestingOnly: (value) => {
    set((state) => ({ filters: { ...state.filters, interestingOnly: value } }));
  },
  setEmergencyOnly: (value) => {
    set((state) => ({ filters: { ...state.filters, emergencyOnly: value } }));
  },
  setHideNonPositioned: (value) => {
    set((state) => ({
      filters: { ...state.filters, hideNonPositioned: value },
    }));
  },
  setGroundTraffic: (mode) => {
    set((state) => ({ filters: { ...state.filters, groundTraffic: mode } }));
  },
  setHideStale: (value) => {
    set((state) => ({ filters: { ...state.filters, hideStale: value } }));
  },
  setLiveSetQuery: (query) => {
    set((state) => ({ filters: { ...state.filters, liveSetQuery: query } }));
  },
  replaceFilters: (filters) => {
    set({ filters });
  },
  clearAll: () => {
    set({ filters: DEFAULT_FILTERS });
  },
}));
