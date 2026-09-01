import { describe, expect, it, vi } from "vitest";

import {
  AIRCRAFT_ICON_NAMES,
  ICON_PIXEL_RATIO,
  registerAircraftIcons,
  svgDataUri,
} from "@/features/map/aircraft/icons/registerIcons";
import {
  AIRCRAFT_ICON_SVGS,
  ICON_PIXELS,
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
  it("registers every icon at the icons' pixel ratio", async () => {
    const style = fakeStyle();
    await registerAircraftIcons(style, loadStub);

    expect([...style.images.keys()].sort()).toEqual(
      AIRCRAFT_ICON_NAMES.map(iconImageId).sort(),
    );
    expect(style.addImage).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(String),
      { pixelRatio: ICON_PIXEL_RATIO },
    );
  });

  it("registers the MLAT ring the layer names", async () => {
    const style = fakeStyle();
    await registerAircraftIcons(style, loadStub);
    expect(style.hasImage(MLAT_RING_IMAGE_ID)).toBe(true);
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
      AIRCRAFT_ICON_NAMES.map((name) => AIRCRAFT_ICON_SVGS[name]).sort(),
    );
  });

  it("propagates a decode failure rather than registering a broken icon", async () => {
    const style = fakeStyle();
    await expect(
      registerAircraftIcons(style, () =>
        Promise.reject(new Error("decode failed")),
      ),
    ).rejects.toThrow("decode failed");
    expect(style.images.size).toBe(0);
  });
});

describe("the silhouette artwork", () => {
  it.each([...AIRCRAFT_ICON_NAMES])(
    "%s is a well-formed square SVG",
    (name) => {
      const markup = AIRCRAFT_ICON_SVGS[name];
      const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
      expect(parsed.querySelector("parsererror")).toBeNull();

      const root = parsed.documentElement;
      expect(root.tagName).toBe("svg");
      expect(root.getAttribute("viewBox")).toBe(
        `0 0 ${ICON_PIXELS} ${ICON_PIXELS}`,
      );
      expect(root.getAttribute("width")).toBe(String(ICON_PIXELS));
      expect(root.getAttribute("height")).toBe(String(ICON_PIXELS));
      expect(root.childElementCount).toBeGreaterThan(0);
    },
  );

  it("distinguishes MLAT with a dash pattern, not only a colour", () => {
    // SPEC §36: never rely exclusively on colour.
    expect(AIRCRAFT_ICON_SVGS["mlat-ring"]).toContain("stroke-dasharray");
  });

  it("gives every icon a distinct namespaced id", () => {
    const ids = AIRCRAFT_ICON_NAMES.map(iconImageId);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id.startsWith("flightsite-aircraft-")).toBe(true);
    }
  });
});
