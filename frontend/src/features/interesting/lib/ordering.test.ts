import { describe, expect, it } from "vitest";

import {
  ATTENTION_SEVERITY_FLOOR,
  SEVERITY_RANK,
  compareInterestingAircraft,
  groupInterestingBySeverity,
  meritsAttention,
  orderInterestingAircraft,
  severityRank,
} from "@/features/interesting/lib/ordering";
import type { AlertSeverity } from "@/lib/api/sightings";
import { makeAircraft } from "@/test/liveAircraftFixtures";

function row(
  icao: string,
  severity: AlertSeverity,
  distanceNm: number | null,
  reasons: string[] = ["Rule: Test"],
) {
  return makeAircraft({
    icao,
    distance_nm: distanceNm,
    interesting: { severity, reasons },
  });
}

function icaosOf(views: ReturnType<typeof row>[]): string[] {
  return orderInterestingAircraft(views).map((entry) => entry.aircraft.icao);
}

describe("severityRank", () => {
  it("ranks the §2.8 ladder in ascending order of seriousness", () => {
    expect(SEVERITY_RANK.info).toBeLessThan(SEVERITY_RANK.interesting);
    expect(SEVERITY_RANK.interesting).toBeLessThan(SEVERITY_RANK.high);
    expect(SEVERITY_RANK.high).toBeLessThan(SEVERITY_RANK.critical);
  });

  it("does not fall back on the string ordering the enum would give", () => {
    // "critical" < "info" alphabetically; the whole reason the ladder is an
    // explicit table on both sides of the wire.
    expect(severityRank("critical")).toBeGreaterThan(severityRank("info"));
  });

  it("puts a severity this build has never heard of at the bottom", () => {
    const unknown = "catastrophic" as AlertSeverity;
    expect(severityRank(unknown)).toBe(0);
  });
});

describe("orderInterestingAircraft", () => {
  it("keeps only aircraft with an active match", () => {
    const views = [
      makeAircraft({ icao: "aaaaaa" }),
      row("bbbbbb", "info", 5),
      makeAircraft({ icao: "cccccc" }),
    ];
    expect(icaosOf(views)).toEqual(["bbbbbb"]);
  });

  it("returns an empty list when nothing is matching", () => {
    expect(orderInterestingAircraft([makeAircraft()])).toEqual([]);
  });

  it("orders by severity before distance", () => {
    // The far critical aircraft outranks the close info one: severity is the
    // primary key, so distance never promotes a lesser match.
    const views = [
      row("aaaaaa", "info", 1),
      row("bbbbbb", "critical", 400),
      row("cccccc", "high", 200),
      row("dddddd", "interesting", 2),
    ];
    expect(icaosOf(views)).toEqual(["bbbbbb", "cccccc", "dddddd", "aaaaaa"]);
  });

  it("orders by distance ascending within one severity band", () => {
    const views = [
      row("aaaaaa", "high", 90),
      row("bbbbbb", "high", 3),
      row("cccccc", "high", 41),
    ];
    expect(icaosOf(views)).toEqual(["bbbbbb", "cccccc", "aaaaaa"]);
  });

  it("sorts an unknown distance last within its band, not first", () => {
    // No distance means no position. A panel that ranked the aircraft it
    // cannot place above the one overhead would answer the wrong question,
    // and the backend's ordering makes the same call.
    const views = [
      row("aaaaaa", "high", null),
      row("bbbbbb", "high", 120),
      row("cccccc", "high", 4),
    ];
    expect(icaosOf(views)).toEqual(["cccccc", "bbbbbb", "aaaaaa"]);
  });

  it("still ranks an unknown-distance critical above a close info", () => {
    const views = [row("aaaaaa", "info", 1), row("bbbbbb", "critical", null)];
    expect(icaosOf(views)).toEqual(["bbbbbb", "aaaaaa"]);
  });

  it("breaks an exact tie on ICAO so the order is total and stable", () => {
    const views = [
      row("ffffff", "info", 10),
      row("aaaaaa", "info", 10),
      row("cccccc", "info", 10),
    ];
    expect(icaosOf(views)).toEqual(["aaaaaa", "cccccc", "ffffff"]);
  });

  it("pairs each row with the match that put it there", () => {
    const [entry] = orderInterestingAircraft([
      row("aaaaaa", "critical", 3, [
        "Emergency squawk 7700 (general emergency)",
      ]),
    ]);
    expect(entry?.interesting.severity).toBe("critical");
    expect(entry?.interesting.reasons).toEqual([
      "Emergency squawk 7700 (general emergency)",
    ]);
    expect(entry?.aircraft.icao).toBe("aaaaaa");
  });
});

describe("meritsAttention (R1-10)", () => {
  it("draws the line below `interesting`, so `info` is not attention-worthy", () => {
    expect(meritsAttention("info")).toBe(false);
    expect(meritsAttention("interesting")).toBe(true);
    expect(meritsAttention("high")).toBe(true);
    expect(meritsAttention("critical")).toBe(true);
  });

  it("treats no match, and the wire's empty-string form, as no attention", () => {
    expect(meritsAttention(null)).toBe(false);
    expect(meritsAttention(undefined)).toBe(false);
    expect(meritsAttention("")).toBe(false);
  });

  it("names the floor rather than hard-coding it twice", () => {
    expect(ATTENTION_SEVERITY_FLOOR).toBe("interesting");
  });
});

describe("groupInterestingBySeverity (R1-10)", () => {
  it("splits at the attention floor, keeping panel order inside each group", () => {
    const rows = orderInterestingAircraft([
      row("aaaaaa", "info", 2),
      row("bbbbbb", "critical", 40),
      row("cccccc", "info", 1),
      row("dddddd", "high", 30),
    ]);
    const { prominent, info } = groupInterestingBySeverity(rows);

    expect(prominent.map((entry) => entry.aircraft.icao)).toEqual([
      "bbbbbb",
      "dddddd",
    ]);
    // Nothing is discarded — the info matches are a second group, in the
    // same severity-then-distance order the panel always uses.
    expect(info.map((entry) => entry.aircraft.icao)).toEqual([
      "cccccc",
      "aaaaaa",
    ]);
  });

  it("hands back two empty groups for an empty list", () => {
    expect(groupInterestingBySeverity([])).toEqual({
      prominent: [],
      info: [],
    });
  });
});

describe("compareInterestingAircraft", () => {
  it("is symmetric about equal entries", () => {
    const a = {
      aircraft: row("aaaaaa", "high", 10),
      interesting: { severity: "high" as const, reasons: [] },
    };
    expect(compareInterestingAircraft(a, a)).toBe(0);
  });
});
