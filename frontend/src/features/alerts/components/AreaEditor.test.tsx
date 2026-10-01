/**
 * The area editor's mini-map and its textarea fallback (roadmap slice 089).
 *
 * MapLibre is the global jsdom mock (`test/maplibreGlMock.ts`), so map
 * gestures are driven by emitting the events MapLibre would — `click`,
 * `dblclick`, and `mousedown`/`mousemove`/`mouseup` over a vertex the mock
 * reports under the pointer — and the assertions read the text both inputs
 * share, which is the property that matters: the map and the keyboard
 * fallback can never disagree.
 */
import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AreaEditor } from "@/features/alerts/components/AreaEditor";
import {
  AREA_SOURCE_ID,
  AREA_VERTEX_LAYER_ID,
} from "@/features/alerts/components/AreaDrawLayer";
import { getLastMockMap, resetMapLibreMock } from "@/test/maplibreGlMock";
import { installAlertsApiMock } from "@/test/alertsApiMock";
import { renderWithProviders } from "@/test/test-utils";

beforeEach(() => {
  resetMapLibreMock();
  installAlertsApiMock({});
});

function Harness({
  initial = "",
  onText,
}: {
  initial?: string;
  onText?: (text: string) => void;
}) {
  const [text, setText] = useState(initial);
  return (
    <AreaEditor
      text={text}
      invalid={false}
      onChange={(next) => {
        setText(next);
        onText?.(next);
      }}
    />
  );
}

function renderEditor(initial = "") {
  const onText = vi.fn();
  renderWithProviders(<Harness initial={initial} onText={onText} />);
  const map = getLastMockMap();
  act(() => {
    map.emit("load");
  });
  return { map, onText, user: userEvent.setup() };
}

function lngLat(lng: number, lat: number) {
  return {
    lngLat: { lng, lat },
    point: { x: 0, y: 0 },
    preventDefault: vi.fn(),
  };
}

const textarea = () => screen.getByLabelText("Vertices (longitude, latitude)");

describe("AreaEditor", () => {
  it("draws on the ordinary map, with the receiver rings, named for its purpose", () => {
    const { map } = renderEditor();

    expect(screen.getByRole("application")).toHaveAccessibleName(
      /click to add vertices/i,
    );
    expect(map.getSource(AREA_SOURCE_ID)).toBeDefined();
    expect(map.getLayer(AREA_VERTEX_LAYER_ID)).toBeDefined();
    // Range rings come with `MapLibreMap` itself.
    expect(map.getSource("flightsite-range-rings")).toBeDefined();
    expect(map.doubleClickZoom.disable).toHaveBeenCalled();
  });

  it("adds a vertex per click, rounded, and writes it into the textarea", () => {
    const { map } = renderEditor();

    act(() => {
      map.emit("click", lngLat(-1.123456789, 50.987654321));
      map.emit("click", lngLat(-1, 50.5));
    });

    expect(textarea()).toHaveValue("-1.12346, 50.98765\n-1, 50.5");
    expect(screen.getByText(/2 of 64 vertices/)).toBeInTheDocument();
  });

  it("finishes on double-click, placing one last vertex and no duplicate", () => {
    const { map } = renderEditor("-2, 50\n-1, 50");

    const dbl = lngLat(-1, 51);
    act(() => {
      // A real double-click arrives as click, click, dblclick.
      map.emit("click", dbl);
      map.emit("click", dbl);
      map.emit("dblclick", dbl);
    });

    expect(textarea()).toHaveValue("-2, 50\n-1, 50\n-1, 51");
    expect(dbl.preventDefault).toHaveBeenCalled();
    expect(screen.getByText(/Drag a vertex to move it/)).toBeInTheDocument();
    // Once finished, a click no longer adds anything.
    act(() => {
      map.emit("click", lngLat(0, 0));
    });
    expect(textarea()).toHaveValue("-2, 50\n-1, 50\n-1, 51");
  });

  it("finishes on Enter from the keyboard", () => {
    renderEditor("-2, 50\n-1, 50\n-1, 51");

    // A saved shape opens in edit mode; resume drawing, then finish.
    fireEvent.click(screen.getByRole("button", { name: "Add vertices" }));
    fireEvent.keyDown(screen.getByRole("application"), { key: "Enter" });

    expect(
      screen.getByRole("button", { name: "Add vertices" }),
    ).toBeInTheDocument();
  });

  it("moves a dragged vertex without panning the map or adding a vertex", () => {
    const { map } = renderEditor("-2, 50\n-1, 50\n-1, 51");
    map.renderedFeatures = [{ properties: { index: 1 } }];

    act(() => {
      map.emit("mousedown", lngLat(-1, 50));
      map.emit("mousemove", lngLat(-0.5, 49.5));
      map.emit("mouseup", lngLat(-0.5, 49.5));
      map.emit("click", lngLat(-0.5, 49.5));
    });

    expect(map.dragPan.disable).toHaveBeenCalled();
    expect(map.dragPan.enable).toHaveBeenCalled();
    expect(textarea()).toHaveValue("-2, 50\n-0.5, 49.5\n-1, 51");
  });

  it("ignores a mousedown that is not on a vertex", () => {
    const { map } = renderEditor("-2, 50\n-1, 50\n-1, 51");
    map.renderedFeatures = [];

    act(() => {
      map.emit("mousedown", lngLat(0, 0));
      map.emit("mousemove", lngLat(1, 1));
    });

    expect(map.dragPan.disable).not.toHaveBeenCalled();
    expect(textarea()).toHaveValue("-2, 50\n-1, 50\n-1, 51");
  });

  it("redraws the map from what is typed in the textarea", async () => {
    const { map, user } = renderEditor();

    await user.type(textarea(), "-2, 50{Enter}-1, 50{Enter}-1, 51");

    const shape = map.getSource(AREA_SOURCE_ID)
      ?.data as GeoJSON.FeatureCollection;
    expect(shape.features[0]?.geometry).toEqual({
      type: "Polygon",
      coordinates: [
        [
          [-2, 50],
          [-1, 50],
          [-1, 51],
          [-2, 50],
        ],
      ],
    });
  });

  it("fits a saved area into view once", () => {
    const { map } = renderEditor("-2, 50\n-1, 50\n-1, 51");

    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [-2, 50],
        [-1, 51],
      ],
      expect.objectContaining({ duration: 0 }),
    );
  });

  it("undoes the last vertex and clears the shape", async () => {
    const { user } = renderEditor("-2, 50\n-1, 50\n-1, 51");

    await user.click(screen.getByRole("button", { name: "Undo vertex" }));
    expect(textarea()).toHaveValue("-2, 50\n-1, 50");

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(textarea()).toHaveValue("");
    expect(screen.getByText(/0 of 64 vertices/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish shape" })).toBeDisabled();
  });
});
