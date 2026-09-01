import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { useUiStore } from "@/store/useUiStore";
import { getLastMockChart } from "@/test/echartsMock";

afterEach(() => {
  useUiStore.setState({ theme: "dark" });
});

function themedBarOption(theme: ChartTheme) {
  return {
    color: [theme.series[0]],
    xAxis: { type: "category", data: ["a", "b"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: [1, 2] }],
  };
}

describe("EChart", () => {
  it("renders the chart container with an aria-label and a visually-hidden summary", () => {
    render(
      <EChart
        buildOption={themedBarOption}
        ariaLabel="Widgets by count, bar chart"
        summary="a: 1, b: 2"
      />,
    );

    const chart = screen.getByRole("img", {
      name: "Widgets by count, bar chart",
    });
    expect(chart).toBeInTheDocument();
    expect(screen.getByText("a: 1, b: 2")).toBeInTheDocument();
  });

  it("initializes ECharts once and calls setOption with the built option", () => {
    render(
      <EChart
        buildOption={themedBarOption}
        ariaLabel="Widgets"
        summary="summary"
      />,
    );

    const instance = getLastMockChart();
    expect(instance.setOption).toHaveBeenCalledTimes(1);
    const applied = instance.optionCalls[0] as { color: string[] };
    expect(applied.color).toEqual(["#3987e5"]); // dark-mode default fallback
  });

  it("renders the empty state and never initializes a chart when buildOption returns null", () => {
    render(
      <EChart buildOption={() => null} ariaLabel="Widgets" summary="summary" />,
    );

    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("rebuilds the option (without re-initializing) when the theme toggles", () => {
    render(
      <EChart
        buildOption={themedBarOption}
        ariaLabel="Widgets"
        summary="summary"
      />,
    );

    const instance = getLastMockChart();
    expect(instance.optionCalls).toHaveLength(1);
    expect((instance.optionCalls[0] as { color: string[] }).color).toEqual([
      "#3987e5",
    ]);

    act(() => {
      useUiStore.getState().setTheme("light");
    });

    // Same instance — a theme toggle rebuilds the option, it does not tear
    // down and recreate the chart.
    expect(getLastMockChart()).toBe(instance);
    expect(instance.optionCalls).toHaveLength(2);
    expect((instance.optionCalls[1] as { color: string[] }).color).toEqual([
      "#2a78d6",
    ]);
  });

  it("disposes the chart instance on unmount", () => {
    const { unmount } = render(
      <EChart
        buildOption={themedBarOption}
        ariaLabel="Widgets"
        summary="summary"
      />,
    );
    const instance = getLastMockChart();
    expect(instance.disposed).toBe(false);

    unmount();

    expect(instance.disposed).toBe(true);
  });

  it("forwards a mark click to onMarkClick", () => {
    const onMarkClick = vi.fn();
    render(
      <EChart
        buildOption={themedBarOption}
        ariaLabel="Widgets"
        summary="summary"
        onMarkClick={onMarkClick}
      />,
    );

    const instance = getLastMockChart();
    instance.emit("click", { dataIndex: 1, name: "b", value: 2 });

    expect(onMarkClick).toHaveBeenCalledWith({
      dataIndex: 1,
      name: "b",
      value: 2,
    });
  });
});
