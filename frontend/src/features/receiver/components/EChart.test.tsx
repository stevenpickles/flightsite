import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EChart } from "@/features/receiver/components/EChart";
import { initMock, mockChartInstances } from "@/test/echartsMock";

describe("EChart", () => {
  it("initializes one chart instance and applies the given option", () => {
    render(
      <EChart
        option={{ series: [{ type: "line", data: [1, 2, 3] }] }}
        ariaLabel="Test chart"
      />,
    );

    expect(initMock).toHaveBeenCalledTimes(1);
    expect(mockChartInstances).toHaveLength(1);
    expect(mockChartInstances[0]?.setOption).toHaveBeenCalledWith(
      { series: [{ type: "line", data: [1, 2, 3] }] },
      true,
    );
  });

  it("renders an accessible image role carrying the given label", () => {
    const { getByRole } = render(
      <EChart option={{}} ariaLabel="Messages per second chart" />,
    );

    expect(
      getByRole("img", { name: "Messages per second chart" }),
    ).toBeInTheDocument();
  });

  it("re-applies a changed option to the same instance", () => {
    const { rerender } = render(
      <EChart option={{ series: [] }} ariaLabel="Test chart" />,
    );
    rerender(
      <EChart
        option={{ series: [{ type: "bar", data: [9] }] }}
        ariaLabel="Test chart"
      />,
    );

    expect(mockChartInstances).toHaveLength(1);
    expect(mockChartInstances[0]?.setOption).toHaveBeenLastCalledWith(
      { series: [{ type: "bar", data: [9] }] },
      true,
    );
  });

  it("disposes the chart instance on unmount", () => {
    const { unmount } = render(<EChart option={{}} ariaLabel="Test chart" />);
    const instance = mockChartInstances[0];

    unmount();

    expect(instance?.dispose).toHaveBeenCalledTimes(1);
  });
});
