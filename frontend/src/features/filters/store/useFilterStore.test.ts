import { beforeEach, describe, expect, it } from "vitest";

import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";

beforeEach(() => {
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
});

describe("useFilterStore", () => {
  it("starts at the defaults", () => {
    expect(useFilterStore.getState().filters).toBe(DEFAULT_FILTERS);
  });

  it("setAltitudeRange replaces both bounds together", () => {
    useFilterStore.getState().setAltitudeRange(1000, 30000);
    expect(useFilterStore.getState().filters).toMatchObject({
      altitudeMinFt: 1000,
      altitudeMaxFt: 30000,
    });
  });

  it("setMaxDistanceNm sets an override", () => {
    useFilterStore.getState().setMaxDistanceNm(75);
    expect(useFilterStore.getState().filters.maxDistanceNm).toBe(75);
  });

  it("text setters update their own field only", () => {
    const { setCategoryText, setOperatorText, setOperatorGroupText } =
      useFilterStore.getState();
    setCategoryText("737");
    setOperatorText("BA");
    setOperatorGroupText("Oneworld");
    expect(useFilterStore.getState().filters).toMatchObject({
      categoryText: "737",
      operatorText: "BA",
      operatorGroupText: "Oneworld",
    });
  });

  it("toggleClassification adds then removes a flag", () => {
    useFilterStore.getState().toggleClassification("military");
    expect(useFilterStore.getState().filters.classifications).toEqual([
      "military",
    ]);
    useFilterStore.getState().toggleClassification("military");
    expect(useFilterStore.getState().filters.classifications).toEqual([]);
  });

  it("toggleMissionCategory adds then removes a mission", () => {
    useFilterStore.getState().toggleMissionCategory("medevac");
    expect(useFilterStore.getState().filters.missionCategories).toEqual([
      "medevac",
    ]);
    useFilterStore.getState().toggleMissionCategory("medevac");
    expect(useFilterStore.getState().filters.missionCategories).toEqual([]);
  });

  it("boolean setters toggle their own field", () => {
    const state = useFilterStore.getState();
    state.setInterestingOnly(true);
    state.setEmergencyOnly(true);
    state.setHideNonPositioned(true);
    state.setHideStale(true);
    expect(useFilterStore.getState().filters).toMatchObject({
      interestingOnly: true,
      emergencyOnly: true,
      hideNonPositioned: true,
      hideStale: true,
    });
  });

  it("setGroundTraffic replaces the mode", () => {
    useFilterStore.getState().setGroundTraffic("dim");
    expect(useFilterStore.getState().filters.groundTraffic).toBe("dim");
  });

  it("setLiveSetQuery updates the narrowing text", () => {
    useFilterStore.getState().setLiveSetQuery("BAW");
    expect(useFilterStore.getState().filters.liveSetQuery).toBe("BAW");
  });

  it("replaceFilters swaps the whole object, e.g. restoring from a URL", () => {
    const restored = { ...DEFAULT_FILTERS, hideStale: true };
    useFilterStore.getState().replaceFilters(restored);
    expect(useFilterStore.getState().filters).toBe(restored);
  });

  it("clearAll resets back to the defaults", () => {
    useFilterStore.getState().setHideStale(true);
    useFilterStore.getState().clearAll();
    expect(useFilterStore.getState().filters).toBe(DEFAULT_FILTERS);
  });

  it("every setter replaces the filters object rather than mutating it in place", () => {
    const before = useFilterStore.getState().filters;
    useFilterStore.getState().setHideStale(true);
    const after = useFilterStore.getState().filters;
    expect(after).not.toBe(before);
  });
});
