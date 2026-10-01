/**
 * The Live Map at a phone viewport (roadmap slice 084, issue #227): at
 * 390 x 844 no two Live Map controls overlap, the map keeps at least 60 % of
 * the viewport with nothing expanded, and each bottom-toolbar card opens as
 * a sheet above the toolbar without covering the connection chip.
 *
 * Overlap is measured on rendered bounding boxes rather than asserted from
 * class names, so a regression in any card's own positioning — not just in
 * `PhoneMapControls` — fails here.
 */

import type { Locator, Page } from "@playwright/test";

import { connectionStatusChip, waitForLiveAircraft } from "./support/liveMap";
import { expect, test } from "./support/fixtures";

const VIEWPORT = { width: 390, height: 844 };

test.use({ viewport: VIEWPORT });

interface Box {
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

function intersects(a: Box, b: Box): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

/** Boxes of every *visible* locator given, by name. */
async function boxesOf(entries: [string, Locator][]): Promise<Box[]> {
  const boxes: Box[] = [];
  for (const [name, locator] of entries) {
    if (!(await locator.isVisible())) {
      continue;
    }
    const box = await locator.boundingBox();
    if (box !== null) {
      boxes.push({ name, ...box });
    }
  }
  return boxes;
}

function expectNoOverlap(boxes: Box[]) {
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i]!;
      const b = boxes[j]!;
      expect(
        intersects(a, b),
        `${a.name} overlaps ${b.name}: ${JSON.stringify(a)} ${JSON.stringify(b)}`,
      ).toBe(false);
    }
  }
}

function restingControls(page: Page): [string, Locator][] {
  return [
    ["connection chip", connectionStatusChip(page)],
    ["quick filters", page.getByRole("group", { name: "Quick filters" })],
    [
      "recentre button",
      page.getByRole("button", { name: "Recentre the map on the receiver" }),
    ],
    ["notification pill", page.getByTestId("notification-status-pill")],
    ["display radius hint", page.getByTestId("display-radius-indicator")],
    ["toolbar", page.getByRole("navigation", { name: "Map panels" })],
  ];
}

test.describe("phone Live Map", () => {
  test("no control overlaps another and the map keeps 60 % of the viewport", async ({
    page,
  }) => {
    await page.goto("/");
    await waitForLiveAircraft(page);

    const boxes = await boxesOf(restingControls(page));
    expect(boxes.map((box) => box.name)).toContain("toolbar");
    expectNoOverlap(boxes);

    const map = await page.getByTestId("maplibre-container").boundingBox();
    expect(map).not.toBeNull();
    const covered = boxes.reduce((sum, b) => sum + b.width * b.height, 0);
    const mapVisible = map!.width * map!.height - covered;
    expect(mapVisible / (VIEWPORT.width * VIEWPORT.height)).toBeGreaterThan(
      0.6,
    );
  });

  test("each toolbar card opens alone, above the toolbar", async ({ page }) => {
    await page.goto("/");
    await waitForLiveAircraft(page);
    const toolbar = page.getByRole("navigation", { name: "Map panels" });

    for (const [label, card] of [
      ["Today", "today"],
      ["Layers", "layers"],
      ["Filters", "filters"],
      ["Aircraft", "aircraft"],
      ["Activity", "activity"],
    ] as const) {
      await toolbar.getByRole("button", { name: label }).click();
      const sheet = page.getByTestId(`phone-map-sheet-${card}`);
      await expect(sheet).toBeVisible();
      await expect(
        page.locator('[id^="phone-map-sheet-"]:visible'),
      ).toHaveCount(1);
      expectNoOverlap(
        await boxesOf([...restingControls(page), [`${card} sheet`, sheet]]),
      );
      await toolbar.getByRole("button", { name: label }).click();
      await expect(sheet).toBeHidden();
    }
  });
});
