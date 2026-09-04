import { describe, expect, it } from "vitest";

import {
  decoderPresentation,
  enrichmentBudgetPresentation,
  errorCountPresentation,
  integrityPresentation,
  maintenancePresentation,
  metadataSourcePresentation,
  notificationPresentation,
  overallPresentation,
  recoveryPresentation,
} from "@/features/health/lib/status";

describe("overallPresentation", () => {
  it("maps each roll-up status to a distinct tone", () => {
    expect(overallPresentation("ok").tone).toBe("ok");
    expect(overallPresentation("degraded").tone).toBe("warn");
    expect(overallPresentation("down").tone).toBe("bad");
  });
});

describe("decoderPresentation", () => {
  it("treats an unconfigured decoder as idle, not broken", () => {
    // A first-run install has nothing to be disconnected from.
    expect(decoderPresentation("unconfigured").tone).toBe("idle");
  });

  it("distinguishes connected, unstable and disconnected", () => {
    expect(decoderPresentation("connected").tone).toBe("ok");
    expect(decoderPresentation("degraded").tone).toBe("warn");
    expect(decoderPresentation("down").tone).toBe("bad");
  });
});

describe("integrityPresentation", () => {
  it("reports a never-run check as unknown rather than healthy", () => {
    const presentation = integrityPresentation(null);
    expect(presentation.tone).toBe("unknown");
    expect(presentation.label).toBe("Not yet checked");
  });

  it("reports a failed check as bad", () => {
    expect(integrityPresentation(false).tone).toBe("bad");
  });

  it("reports a passed check as ok", () => {
    expect(integrityPresentation(true).tone).toBe("ok");
  });
});

describe("metadataSourcePresentation", () => {
  it("shows an in-progress import over the stored status", () => {
    expect(metadataSourcePresentation("ok", true).label).toBe("Importing…");
  });

  it("treats a never-imported source as idle", () => {
    expect(metadataSourcePresentation("never_run", false).tone).toBe("idle");
  });

  it("warns on a failed import", () => {
    expect(metadataSourcePresentation("failed", false).tone).toBe("warn");
  });
});

describe("notificationPresentation", () => {
  it("separates granted-and-on from granted-but-disabled", () => {
    expect(notificationPresentation("granted", true).tone).toBe("ok");
    expect(notificationPresentation("granted", false).tone).toBe("idle");
  });

  it("surfaces a browser block as a warning, per SECURITY §5", () => {
    const presentation = notificationPresentation("denied", true);
    expect(presentation.tone).toBe("warn");
    expect(presentation.label).toBe("Blocked by browser");
  });

  it("explains an insecure context rather than calling it unsupported", () => {
    expect(notificationPresentation("insecure-context", true).label).toBe(
      "Needs HTTPS or localhost",
    );
  });

  it("treats never-requested as idle, not a fault", () => {
    expect(notificationPresentation("default", true).tone).toBe("idle");
    expect(notificationPresentation("unsupported", true).tone).toBe("idle");
  });
});

describe("maintenancePresentation", () => {
  it("reports no cycles yet as unknown", () => {
    expect(maintenancePresentation(true, 0).tone).toBe("unknown");
    expect(maintenancePresentation(null, 0).tone).toBe("unknown");
  });

  it("warns when a job failed", () => {
    expect(maintenancePresentation(false, 5).tone).toBe("warn");
  });

  it("reports a healthy run", () => {
    expect(maintenancePresentation(true, 5).tone).toBe("ok");
  });
});

describe("recoveryPresentation", () => {
  it("calls a clean recovery clean", () => {
    expect(recoveryPresentation(0)).toEqual({ tone: "ok", label: "Clean" });
  });

  it("pluralises anomalies correctly", () => {
    expect(recoveryPresentation(1).label).toBe("1 anomaly");
    expect(recoveryPresentation(3).label).toBe("3 anomalies");
  });
});

describe("errorCountPresentation", () => {
  it("is ok when nothing has gone wrong", () => {
    expect(errorCountPresentation(0)).toEqual({ tone: "ok", label: "None" });
  });

  it("warns when errors were captured", () => {
    expect(errorCountPresentation(4)).toEqual({
      tone: "warn",
      label: "4 recent",
    });
  });
});

describe("enrichmentBudgetPresentation", () => {
  it("reports what is left of a capped budget", () => {
    expect(
      enrichmentBudgetPresentation({
        limit: 100,
        used_today: 12,
        remaining: 88,
        resets_at: "2026-09-01T00:00:00.000Z",
      }),
    ).toEqual({ tone: "ok", label: "88 left today" });
  });

  it("says uncapped rather than claiming health for an unlimited budget", () => {
    expect(
      enrichmentBudgetPresentation({
        limit: null,
        used_today: 412,
        remaining: null,
        resets_at: "2026-09-01T00:00:00.000Z",
      }),
    ).toEqual({ tone: "idle", label: "Uncapped" });
  });

  it("warns on a spent budget — a chosen cap being reached is not a fault", () => {
    expect(
      enrichmentBudgetPresentation({
        limit: 50,
        used_today: 50,
        remaining: 0,
        resets_at: "2026-09-01T00:00:00.000Z",
      }),
    ).toEqual({ tone: "warn", label: "Budget spent" });
  });

  it("has nothing to present for a backend that does not report a budget", () => {
    expect(enrichmentBudgetPresentation(undefined)).toBeNull();
  });
});
