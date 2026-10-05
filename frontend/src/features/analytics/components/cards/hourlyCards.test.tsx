/**
 * The three day-granular time-series cards over a single-day window (slice
 * 097). A one-day window used to hand each of them one point, drawn as a
 * line with its marker hidden — an empty plot until hovered. Given the
 * day's hourly breakdown they draw that instead; these tests pin what each
 * one plots and that a sparse line always shows its points.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClassificationActivityCard } from "@/features/analytics/components/cards/ClassificationActivityCard";
import { DailyCountsCard } from "@/features/analytics/components/cards/DailyCountsCard";
import { MaxDistanceCard } from "@/features/analytics/components/cards/MaxDistanceCard";
import { NeverSeenBeforeCard } from "@/features/analytics/components/cards/NeverSeenBeforeCard";
import { ReceiverActivityCard } from "@/features/analytics/components/cards/ReceiverActivityCard";
import type {
  AnalyticsDailyRow,
  AnalyticsHourlyRow,
} from "@/lib/api/analytics";
import { getLastMockChart } from "@/test/echartsMock";

function hourRow(
  hour: number,
  overrides: Partial<AnalyticsHourlyRow> = {},
): AnalyticsHourlyRow {
  return {
    t: `2026-10-05T${String((hour + 4) % 24).padStart(2, "0")}:00:00.000Z`,
    hour,
    sightings: 0,
    unique_aircraft: 0,
    military: 0,
    government: 0,
    law_enforcement: 0,
    new_aircraft: 0,
    messages: null,
    positions: null,
    max_range_nm: null,
    ...overrides,
  };
}

/** A day three hours old: two with traffic, one quiet, one not begun. */
const HOURLY: AnalyticsHourlyRow[] = [
  hourRow(0, {
    sightings: 3,
    unique_aircraft: 2,
    military: 1,
    government: 0,
    law_enforcement: 2,
    new_aircraft: 2,
    messages: 41_000,
    positions: 3_200,
    max_range_nm: 188.2,
  }),
  hourRow(1, {
    sightings: 0,
    unique_aircraft: 1,
    messages: 12_000,
    positions: 900,
    max_range_nm: null,
  }),
  hourRow(2, {
    sightings: 5,
    unique_aircraft: 4,
    military: 0,
    government: 3,
    law_enforcement: 0,
    new_aircraft: 1,
    messages: 66_500,
    positions: 5_100,
    max_range_nm: 224.9,
  }),
  hourRow(3, {
    sightings: null,
    unique_aircraft: null,
    military: null,
    government: null,
    law_enforcement: null,
    new_aircraft: null,
  }),
];

function dailyRow(
  overrides: Partial<AnalyticsDailyRow> = {},
): AnalyticsDailyRow {
  return {
    day: "2026-10-05",
    complete: true,
    unique_aircraft: 6,
    new_aircraft: 1,
    sightings: 8,
    interesting: 0,
    military: 0,
    government: 0,
    law_enforcement: 0,
    max_range_nm: 224.9,
    busiest_hour: null,
    receiver_messages: 119_500,
    receiver_positions: 9_200,
    receiver_aircraft_max: 4,
    receiver_max_range_nm: 224.9,
    ...overrides,
  };
}

interface PlottedOption {
  xAxis: { data: string[]; name?: string };
  series: Array<{
    name?: string;
    type: string;
    data: Array<number | null>;
    showSymbol?: boolean;
    stack?: string;
  }>;
}

function lastOption(): PlottedOption {
  const option = getLastMockChart().optionCalls.at(-1);
  if (option === undefined) {
    throw new Error("the chart was never given an option");
  }
  return option as PlottedOption;
}

describe("DailyCountsCard over a single day", () => {
  it("draws aircraft and sightings as bars per hour, future hours empty", () => {
    render(
      <DailyCountsCard
        items={[dailyRow()]}
        hourly={HOURLY}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Aircraft & sightings by hour" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Aircraft and sightings by hour, bar chart",
      }),
    ).toBeInTheDocument();

    const option = lastOption();
    expect(option.xAxis.data).toEqual(["00", "01", "02", "03"]);
    expect(option.xAxis.name).toBe("hour");
    expect(option.series.map((series) => [series.name, series.type])).toEqual([
      ["Aircraft", "bar"],
      ["Sightings", "bar"],
    ]);
    expect(option.series[0]?.data).toEqual([2, 1, 4, null]);
    expect(option.series[1]?.data).toEqual([3, 0, 5, null]);
  });

  it("summarises only the hours that had traffic", () => {
    render(
      <DailyCountsCard
        items={[dailyRow()]}
        hourly={HOURLY}
        isLoading={false}
      />,
    );
    const summary = screen.getByText(/Aircraft heard and sightings started/);
    expect(summary).toHaveTextContent("00:00 — 2 aircraft, 3 sightings");
    expect(summary).toHaveTextContent("01:00 — 1 aircraft, 0 sightings");
    expect(summary).toHaveTextContent("02:00 — 4 aircraft, 5 sightings");
    expect(summary).not.toHaveTextContent("03:00");
  });

  it("shows the empty state when the day has no buckets at all", () => {
    render(
      <DailyCountsCard items={[dailyRow()]} hourly={[]} isLoading={false} />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("keeps the daily title and lines when no hourly breakdown is given", () => {
    render(<DailyCountsCard items={[dailyRow()]} isLoading={false} />);
    expect(
      screen.getByRole("heading", { name: "Daily aircraft & sighting counts" }),
    ).toBeInTheDocument();
    const option = lastOption();
    expect(option.series.every((series) => series.type === "line")).toBe(true);
    // One day is one point: its marker must be drawn or the plot is empty.
    expect(option.series.every((series) => series.showSymbol === true)).toBe(
      true,
    );
  });
});

describe("MaxDistanceCard over a single day", () => {
  it("plots the farthest detection per hour, with markers and gaps", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow()]}
        hourly={HOURLY}
        units="aviation"
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Maximum detection distance by hour, line chart",
      }),
    ).toBeInTheDocument();
    const option = lastOption();
    expect(option.xAxis.data).toEqual(["00", "01", "02", "03"]);
    expect(option.series[0]?.data).toEqual([188.2, null, 224.9, null]);
    expect(option.series[0]?.showSymbol).toBe(true);
    expect(
      screen.getByText(/by hour, in nm: 00:00 — 188.2 nm; 02:00 — 224.9 nm/),
    ).toBeInTheDocument();
  });

  it("converts the hourly ranges for metric units", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow()]}
        hourly={[hourRow(0, { max_range_nm: 100 })]}
        units="metric"
        isLoading={false}
      />,
    );
    expect(lastOption().series[0]?.data).toEqual([185.2]);
  });

  it("shows the empty state when no hour has a range", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow()]}
        hourly={[hourRow(0), hourRow(1)]}
        units="aviation"
        isLoading={false}
      />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });
});

describe("ReceiverActivityCard over a single day", () => {
  it("plots messages and positions per hour, with markers", () => {
    render(
      <ReceiverActivityCard
        items={[dailyRow()]}
        hourly={HOURLY}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Receiver messages and positions by hour, line chart",
      }),
    ).toBeInTheDocument();
    const option = lastOption();
    expect(option.xAxis.data).toEqual(["00", "01", "02", "03"]);
    expect(option.series.map((series) => series.name)).toEqual([
      "Messages",
      "Positions",
    ]);
    expect(option.series[0]?.data).toEqual([41_000, 12_000, 66_500, null]);
    expect(option.series[1]?.data).toEqual([3_200, 900, 5_100, null]);
    expect(option.series.every((series) => series.showSymbol === true)).toBe(
      true,
    );
  });

  it("shows the empty state when no hour has receiver metrics", () => {
    render(
      <ReceiverActivityCard
        items={[dailyRow()]}
        hourly={[hourRow(0), hourRow(1)]}
        isLoading={false}
      />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });
});

describe("ClassificationActivityCard over a single day", () => {
  it("stacks the three classes per hour, future hours empty", () => {
    render(
      <ClassificationActivityCard
        series={[dailyRow()]}
        hourly={HOURLY}
        complete
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Military, government and law-enforcement activity by hour, stacked bar chart",
      }),
    ).toBeInTheDocument();
    const option = lastOption();
    expect(option.xAxis.data).toEqual(["00", "01", "02", "03"]);
    expect(option.xAxis.name).toBe("hour");
    expect(option.series.map((series) => series.name)).toEqual([
      "Military",
      "Government",
      "Law enforcement",
    ]);
    expect(
      option.series.every(
        (series) => series.type === "bar" && series.stack === "classification",
      ),
    ).toBe(true);
    expect(option.series[0]?.data).toEqual([1, 0, 0, null]);
    expect(option.series[1]?.data).toEqual([0, 0, 3, null]);
    expect(option.series[2]?.data).toEqual([2, 0, 0, null]);
  });

  it("summarises only the hours that had classified traffic", () => {
    render(
      <ClassificationActivityCard
        series={[dailyRow()]}
        hourly={HOURLY}
        isLoading={false}
      />,
    );
    const summary = screen.getByText(/sightings by hour:/);
    expect(summary).toHaveTextContent(
      "00:00 — 1 military, 0 government, 2 law-enforcement",
    );
    expect(summary).toHaveTextContent(
      "02:00 — 0 military, 3 government, 0 law-enforcement",
    );
    expect(summary).not.toHaveTextContent("01:00");
  });

  it("says so when the day has had none", () => {
    render(
      <ClassificationActivityCard
        series={[dailyRow()]}
        hourly={[hourRow(0), hourRow(1)]}
        isLoading={false}
      />,
    );
    expect(
      screen.getByText(
        "No military, government or law-enforcement activity so far in this day.",
      ),
    ).toBeInTheDocument();
  });

  it("draws an empty day rather than failing on a payload without the fields", () => {
    // The hourly endpoint as slice 097 shipped it had none of these.
    const legacy = HOURLY.map((row) => {
      const copy = { ...row };
      delete copy.military;
      delete copy.government;
      delete copy.law_enforcement;
      delete copy.new_aircraft;
      return copy;
    });
    render(
      <ClassificationActivityCard
        series={[dailyRow()]}
        hourly={legacy}
        isLoading={false}
      />,
    );
    expect(lastOption().series[0]?.data).toEqual([null, null, null, null]);
  });

  it("keeps one stacked bar per day when no hourly breakdown is given", () => {
    render(
      <ClassificationActivityCard
        series={[dailyRow({ military: 4 })]}
        complete
        isLoading={false}
      />,
    );
    expect(
      screen.getByRole("img", {
        name: "Military, government and law-enforcement activity over time, stacked bar chart",
      }),
    ).toBeInTheDocument();
    expect(lastOption().xAxis.data).toEqual(["2026-10-05"]);
    expect(lastOption().series[0]?.data).toEqual([4]);
  });
});

describe("NeverSeenBeforeCard over a single day", () => {
  it("draws the aircraft first heard in each hour, future hours empty", () => {
    render(
      <NeverSeenBeforeCard
        items={[dailyRow()]}
        hourly={HOURLY}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "New aircraft never seen before, by hour, bar chart",
      }),
    ).toBeInTheDocument();
    const option = lastOption();
    expect(option.xAxis.data).toEqual(["00", "01", "02", "03"]);
    expect(option.xAxis.name).toBe("hour");
    expect(option.series[0]?.type).toBe("bar");
    expect(option.series[0]?.data).toEqual([2, 0, 1, null]);
    expect(
      screen.getByText(/by hour, 3 total: 00:00 — 2; 02:00 — 1/),
    ).toBeInTheDocument();
  });

  it("says so when nothing new has been heard yet", () => {
    render(
      <NeverSeenBeforeCard
        items={[dailyRow()]}
        hourly={[hourRow(0), hourRow(1)]}
        isLoading={false}
      />,
    );
    expect(
      screen.getByText(
        "No aircraft were heard for the first time so far in this day.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps one bar per day when no hourly breakdown is given", () => {
    render(<NeverSeenBeforeCard items={[dailyRow()]} isLoading={false} />);
    expect(
      screen.getByRole("img", {
        name: "New aircraft never seen before, by day, bar chart",
      }),
    ).toBeInTheDocument();
    expect(lastOption().series[0]?.data).toEqual([1]);
  });
});

describe("line markers on the daily series", () => {
  it("are drawn for a week of days and hidden for a year of them", () => {
    const week = Array.from({ length: 7 }, (_, index) =>
      dailyRow({ day: `2026-10-0${index + 1}` }),
    );
    const { unmount } = render(
      <ReceiverActivityCard items={week} isLoading={false} />,
    );
    expect(lastOption().series[0]?.showSymbol).toBe(true);
    unmount();

    const year = Array.from({ length: 365 }, (_, index) =>
      dailyRow({ day: `day-${index}` }),
    );
    render(<ReceiverActivityCard items={year} isLoading={false} />);
    expect(lastOption().series[0]?.showSymbol).toBe(false);
  });
});
