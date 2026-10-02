import { describe, expect, it, vi } from "vitest";

import {
  AIRCRAFT_ICON_IMAGE_IDS,
  ICON_PIXEL_RATIO,
  registerAircraftIcons,
  svgDataUri,
} from "@/features/map/aircraft/icons/registerIcons";
import {
  AIRCRAFT_ICON_SHAPES,
  AIRCRAFT_ICON_SVGS,
  ICON_PALETTE_NAMES,
  iconImageId,
  MLAT_RING_IMAGE_ID,
} from "@/features/map/aircraft/icons/silhouettes";

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

describe("svgDataUri", () => {
  it("encodes markup as a loadable SVG data URI", () => {
    const uri = svgDataUri('<svg><path d="M0 0 L1 1"/></svg>');
    expect(uri.startsWith("data:image/svg+xml;charset=utf-8,")).toBe(true);
    expect(decodeURIComponent(uri.split(",")[1] ?? "")).toBe(
      '<svg><path d="M0 0 L1 1"/></svg>',
    );
  });

  it("escapes the characters a URI cannot carry raw", () => {
    expect(svgDataUri("<svg/>")).toContain("%3Csvg%2F%3E");
  });
});

describe("registerAircraftIcons", () => {
  it("registers every shape in every palette, plus the MLAT ring", async () => {
    const style = fakeStyle();
    await registerAircraftIcons(style, loadStub);

    const expected = AIRCRAFT_ICON_SHAPES.flatMap((shape) =>
      ICON_PALETTE_NAMES.map((palette) => iconImageId(shape, palette)),
    );
    expected.push(MLAT_RING_IMAGE_ID);
    expect([...style.images.keys()].sort()).toEqual(expected.sort());
    expect(style.images.size).toBe(
      AIRCRAFT_ICON_SHAPES.length * ICON_PALETTE_NAMES.length + 1,
    );
  });

  it("registers at the icons' pixel ratio", async () => {
    const style = fakeStyle();
    await registerAircraftIcons(style, loadStub);
    expect(style.addImage).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(String),
      { pixelRatio: ICON_PIXEL_RATIO },
    );
  });

  it("skips icons the style already carries", async () => {
    // Called again after every style load; re-adding would throw on a
    // duplicate id.
    const style = fakeStyle();
    await registerAircraftIcons(style, loadStub);
    style.addImage.mockClear();

    await expect(
      registerAircraftIcons(style, loadStub),
    ).resolves.toBeUndefined();
    expect(style.addImage).not.toHaveBeenCalled();
  });

  it("passes each icon's own markup through the loader", async () => {
    const style = fakeStyle();
    const seen: string[] = [];
    await registerAircraftIcons(style, async (uri) => {
      seen.push(decodeURIComponent(uri.split(",")[1] ?? ""));
      return uri as unknown as HTMLImageElement;
    });
    expect(seen.sort()).toEqual(
      AIRCRAFT_ICON_IMAGE_IDS.map((id) => AIRCRAFT_ICON_SVGS[id]).sort(),
    );
  });

  it("propagates a decode failure, naming the icon, rather than registering a broken one", async () => {
    const style = fakeStyle();
    const failing = iconImageId("fighter", "military");
    await expect(
      registerAircraftIcons(style, (uri) =>
        uri === svgDataUri(AIRCRAFT_ICON_SVGS[failing] ?? "")
          ? Promise.reject(new Error("decode failed"))
          : Promise.resolve(uri as unknown as HTMLImageElement),
      ),
    ).rejects.toThrow(`failed to decode icon ${failing}`);
    expect(style.images.has(failing)).toBe(false);
  });
});
