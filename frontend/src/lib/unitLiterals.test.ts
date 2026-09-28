/**
 * Guard for the receiver's units preference (roadmap slice 081, issue #224).
 *
 * Storage and the wire format are nm/ft/kt, and every surface converts for
 * display through a unit-aware formatter. The easy way to break that is a
 * template literal or JSX text that glues a canonical suffix onto a number —
 * `${value} nm`, `{value} ft` — which prints aviation units whatever the
 * preference says. This test fails on any such literal outside the modules
 * whose job is to choose the unit.
 */

import { describe, expect, it } from "vitest";

const SOURCES = import.meta.glob<string>("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** An interpolation or JSX expression immediately followed by a canonical
 * unit suffix. */
const HARD_CODED_UNIT = /\}\s(ft|nm|kt|fpm)\b/;

/**
 * Files allowed to spell canonical units, and why.
 *
 * - The formatters pick the suffix from the units preference.
 * - The validation messages describe *input* bounds. Settings and the rule
 *   builder take canonical units with a conversion hint beside each field
 *   (the 2026-09-20 site review's decision R4-13), so the bound is stated in
 *   the unit the field accepts.
 */
const ALLOWED = new Set([
  "/src/features/aircraft-detail/lib/format.ts",
  "/src/features/feeders/lib/format.ts",
  "/src/features/map/geo/rings.ts",
  "/src/features/map/labels/labelContent.ts",
  "/src/features/receiver/lib/format.ts",
  "/src/features/today/lib/format.ts",
  "/src/features/alerts/lib/conditions.ts",
  "/src/features/settings/lib/validation.ts",
  "/src/features/setup/lib/validation.ts",
]);

function isTestOnly(path: string): boolean {
  return /\.test\.tsx?$/.test(path) || path.startsWith("/src/test/");
}

function isComment(line: string): boolean {
  const trimmed = line.trimStart();
  return (
    trimmed.startsWith("*") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/*")
  );
}

describe("unit literals", () => {
  it("finds the source tree", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
  });

  it("keeps canonical unit suffixes inside the unit-aware formatters", () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(SOURCES)) {
      if (ALLOWED.has(path) || isTestOnly(path)) {
        continue;
      }
      source.split("\n").forEach((line, index) => {
        if (!isComment(line) && HARD_CODED_UNIT.test(line)) {
          offenders.push(`${path}:${index + 1}: ${line.trim()}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it("allows only files that exist", () => {
    for (const path of ALLOWED) {
      expect(SOURCES[path], path).toBeTypeOf("string");
    }
  });
});
