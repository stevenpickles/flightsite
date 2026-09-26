import { describe, expect, it } from "vitest";

import {
  feederStatePresentation,
  observabilityNote,
  worstFeederState,
} from "@/features/feeders/lib/status";

describe("feederStatePresentation", () => {
  it("maps every state to a tone and label", () => {
    expect(feederStatePresentation("up")).toEqual({ tone: "ok", label: "Up" });
    expect(feederStatePresentation("degraded")).toEqual({
      tone: "warn",
      label: "Degraded",
    });
    expect(feederStatePresentation("down")).toEqual({
      tone: "bad",
      label: "Down",
    });
    expect(feederStatePresentation("unknown")).toEqual({
      tone: "unknown",
      label: "Unknown",
    });
  });
});

describe("worstFeederState", () => {
  it("is unknown for an empty list", () => {
    expect(worstFeederState([])).toBe("unknown");
  });

  it("prefers down over everything else", () => {
    expect(worstFeederState(["up", "degraded", "down", "unknown"])).toBe(
      "down",
    );
  });

  it("prefers degraded over unknown and up", () => {
    expect(worstFeederState(["up", "unknown", "degraded"])).toBe("degraded");
  });

  it("prefers unknown over up", () => {
    expect(worstFeederState(["up", "unknown"])).toBe("unknown");
  });

  it("is up only when every state is up", () => {
    expect(worstFeederState(["up", "up"])).toBe("up");
  });
});

describe("observabilityNote", () => {
  it("explains the socket-off case", () => {
    expect(observabilityNote("none")).toBe(
      "Needs the Docker socket — see Settings",
    );
  });

  it("is null for http and docker observability", () => {
    expect(observabilityNote("http")).toBeNull();
    expect(observabilityNote("docker")).toBeNull();
  });
});
