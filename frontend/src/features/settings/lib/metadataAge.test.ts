import { describe, expect, it } from "vitest";

import { overallMetadataAge } from "@/features/settings/lib/metadataAge";
import { metadataSource } from "@/test/metadataApiMock";

describe("overallMetadataAge", () => {
  it("is null when there are no sources at all", () => {
    expect(overallMetadataAge([])).toBeNull();
  });

  it("is null when no source has ever succeeded — the fresh-install 'never' state", () => {
    const sources = [
      metadataSource({ name: "mictronics", status: "never-run" }),
      metadataSource({ name: "faa", status: "never-run" }),
    ];

    expect(overallMetadataAge(sources)).toBeNull();
  });

  it("is the single source's last success when only one has ever run", () => {
    const sources = [
      metadataSource({
        name: "mictronics",
        status: "ok",
        last_success_ms: 1_000,
      }),
      metadataSource({ name: "faa", status: "never-run" }),
    ];

    expect(overallMetadataAge(sources)).toBe(1_000);
  });

  it("is the maximum last_success_ms across every source", () => {
    const sources = [
      metadataSource({
        name: "mictronics",
        status: "ok",
        last_success_ms: 5_000,
      }),
      metadataSource({ name: "faa", status: "ok", last_success_ms: 9_000 }),
    ];

    expect(overallMetadataAge(sources)).toBe(9_000);
  });

  it("keeps a source's earlier success even while it is currently failed", () => {
    // SPEC §27: a failed import leaves the previous dataset — and its
    // last_success_ms — intact, so the overall age must not drop it either.
    const sources = [
      metadataSource({
        name: "faa",
        status: "failed",
        last_success_ms: 3_000,
        last_error: "upstream unreachable",
      }),
    ];

    expect(overallMetadataAge(sources)).toBe(3_000);
  });
});
