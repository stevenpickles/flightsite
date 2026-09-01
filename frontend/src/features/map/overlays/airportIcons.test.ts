import { describe, expect, it, vi } from "vitest";

import {
  AIRPORT_ICON_SVGS,
  airportIconImageId,
  registerAirportIcons,
} from "@/features/map/overlays/airportIcons";
import type { AirportSizeClass } from "@/lib/api/overlays";

const SIZE_CLASSES: AirportSizeClass[] = [
  "large",
  "medium",
  "small",
  "heliport",
];

function fakeStyle() {
  const images = new Map<string, unknown>();
  return {
    images,
    hasImage: vi.fn((id: string) => images.has(id)),
    addImage: vi.fn((id: string, image: unknown) => {
      if (images.has(id)) {
        throw new Error(`duplicate image ${id}`);
      }
      images.set(id, image);
    }),
  };
}

const loadStub = vi.fn(
  async (uri: string) => uri as unknown as HTMLImageElement,
);

describe("registerAirportIcons", () => {
  it("registers a glyph for every size class", async () => {
    const style = fakeStyle();
    await registerAirportIcons(style, loadStub);

    expect([...style.images.keys()].sort()).toEqual(
      SIZE_CLASSES.map(airportIconImageId).sort(),
    );
  });

  it("skips icons the style already carries", async () => {
    const style = fakeStyle();
    await registerAirportIcons(style, loadStub);
    style.addImage.mockClear();

    await expect(
      registerAirportIcons(style, loadStub),
    ).resolves.toBeUndefined();
    expect(style.addImage).not.toHaveBeenCalled();
  });

  it("passes each size class's own markup through the loader", async () => {
    const style = fakeStyle();
    const seen: string[] = [];
    await registerAirportIcons(style, async (uri) => {
      seen.push(decodeURIComponent(uri.split(",")[1] ?? ""));
      return uri as unknown as HTMLImageElement;
    });
    expect(seen.sort()).toEqual(
      SIZE_CLASSES.map((sizeClass) => AIRPORT_ICON_SVGS[sizeClass]).sort(),
    );
  });

  it("propagates a decode failure rather than registering a broken icon", async () => {
    const style = fakeStyle();
    await expect(
      registerAirportIcons(style, () =>
        Promise.reject(new Error("decode failed")),
      ),
    ).rejects.toThrow("decode failed");
    expect(style.images.size).toBe(0);
  });
});

describe("the airport glyph artwork", () => {
  it.each(SIZE_CLASSES)("%s is a well-formed SVG", (sizeClass) => {
    const markup = AIRPORT_ICON_SVGS[sizeClass];
    const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
    expect(parsed.querySelector("parsererror")).toBeNull();
    expect(parsed.documentElement.tagName).toBe("svg");
    expect(parsed.documentElement.childElementCount).toBeGreaterThan(0);
  });

  it("gives every size class a distinct namespaced image id", () => {
    const ids = SIZE_CLASSES.map(airportIconImageId);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id.startsWith("flightsite-airport-")).toBe(true);
    }
  });

  it("gives every size class visually distinct markup", () => {
    const markups = SIZE_CLASSES.map(
      (sizeClass) => AIRPORT_ICON_SVGS[sizeClass],
    );
    expect(new Set(markups).size).toBe(markups.length);
  });
});
