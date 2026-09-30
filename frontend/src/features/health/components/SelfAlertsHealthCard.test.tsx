import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { SelfAlertsHealthCard } from "@/features/health/components/SelfAlertsHealthCard";
import type { DiagnosticsSelfAlerts } from "@/lib/api/diagnostics";

function selfAlerts(
  overrides: Partial<DiagnosticsSelfAlerts> = {},
): DiagnosticsSelfAlerts {
  return {
    conditions: {
      decoder_down: { enabled: true, state: "ok", minutes: 5 },
      message_rate: {
        enabled: true,
        state: "ok",
        minutes: 15,
        share_pct: 40,
        baseline_msgs_s: 88.5,
        baseline_weeks: 4,
      },
      feeder_offline: { enabled: true, state: "ok", count: 0 },
    },
    active: [],
    ...overrides,
  };
}

function renderCard(data: DiagnosticsSelfAlerts) {
  return render(
    <MemoryRouter>
      <SelfAlertsHealthCard selfAlerts={data} timezone="UTC" />
    </MemoryRouter>,
  );
}

describe("SelfAlertsHealthCard", () => {
  it("says so when nothing is wrong", () => {
    renderCard(selfAlerts());
    expect(screen.getByText("None active")).toBeInTheDocument();
    expect(
      screen.getByText(/nothing is wrong with the station/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /self-alert settings/i }),
    ).toHaveAttribute("href", "/settings#settings-self-alerts");
  });

  it("lists every active condition with the time it began", () => {
    renderCard(
      selfAlerts({
        active: [
          {
            condition: "decoder_down",
            since: "2026-09-29T02:10:00Z",
            severity: "high",
            subject: null,
            label: null,
          },
          {
            condition: "feeder_offline",
            since: "2026-09-29T01:00:00Z",
            severity: "high",
            subject: "fr24",
            label: "FlightRadar24",
          },
        ],
      }),
    );

    expect(screen.getByText("2 active")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /active self-alerts/i });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Decoder down");
    expect(rows[0]).toHaveTextContent(/since .*02:10/);
    expect(rows[1]).toHaveTextContent("Feed offline: FlightRadar24");
  });

  it("explains a message-rate baseline that is still learning", () => {
    renderCard(
      selfAlerts({
        conditions: {
          message_rate: {
            enabled: true,
            state: "learning",
            baseline_weeks: 1,
          },
        },
      }),
    );
    expect(
      screen.getByText(/learning this hour's baseline \(1 of 2 weeks/i),
    ).toBeInTheDocument();
  });

  it("reads Off rather than healthy when every condition is switched off", () => {
    renderCard(
      selfAlerts({
        conditions: {
          decoder_down: { enabled: false, state: "disabled" },
          message_rate: { enabled: false, state: "disabled" },
          feeder_offline: { enabled: false, state: "disabled" },
        },
      }),
    );
    expect(screen.getByText("Off")).toBeInTheDocument();
    expect(
      screen.getByText(/every self-alert is switched off/i),
    ).toBeInTheDocument();
  });
});
