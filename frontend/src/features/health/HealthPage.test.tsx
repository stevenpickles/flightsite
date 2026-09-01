import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import {
  database,
  decoder,
  diagnostics,
  errorEntry,
  installDiagnosticsApiMock,
  metadata,
  metadataSource,
} from "@/test/diagnosticsApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  useNotificationStore.getState().reset();
});

describe("HealthPage", () => {
  it("renders every SPEC §67 item on a healthy install", async () => {
    installDiagnosticsApiMock();
    renderApp("/health");

    // Awaiting the summary group, not the heading: the loading state also
    // renders an <h1>Health</h1>, so a heading query would resolve too early.
    const summary = await screen.findByRole("group", {
      name: "Health summary",
    });
    expect(
      screen.getByRole("heading", { name: "Health", level: 1 }),
    ).toBeInTheDocument();

    // Decoder connection state, and the last successful aircraft update.
    expect(within(summary).getAllByText("Connected").length).toBeGreaterThan(0);
    expect(within(summary).getByText("just now")).toBeInTheDocument();
    // Backend uptime and version.
    expect(within(summary).getByText("1d 1h")).toBeInTheDocument();
    expect(within(summary).getByText("0.9.2")).toBeInTheDocument();
    expect(within(summary).getByText("Schema 0012")).toBeInTheDocument();
    // Database size and free disk space.
    expect(within(summary).getByText("256 MB")).toBeInTheDocument();
    expect(within(summary).getByText("12 GB")).toBeInTheDocument();
    // Metadata age, and WebSocket state.
    expect(within(summary).getByText("2d 2h")).toBeInTheDocument();
    expect(
      within(summary).getByText("0 dropped since start-up"),
    ).toBeInTheDocument();

    // Useful row counts.
    expect(await screen.findByText("Sighting tracks")).toBeInTheDocument();
    expect(screen.getByText("902,114")).toBeInTheDocument();

    // Database health.
    expect(screen.getByText("Integrity check")).toBeInTheDocument();

    // Recent errors, per category.
    expect(
      screen.getByRole("heading", { name: "Ingestion errors" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Database errors" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Enrichment errors" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "WebSocket errors" }),
    ).toBeInTheDocument();
  });

  it("shows the overall status as healthy when nothing is wrong", async () => {
    installDiagnosticsApiMock();
    renderApp("/health");

    expect(await screen.findByText("Healthy")).toBeInTheDocument();
  });
});

describe("HealthPage degraded states", () => {
  it("reports a disconnected decoder with its error, not a blank card", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        status: "down",
        decoder: decoder({
          state: "down",
          last_error: "connection refused",
          consecutive_failures: 7,
          last_success: null,
        }),
      }),
    });
    renderApp("/health");

    expect(await screen.findByText("Problem")).toBeInTheDocument();
    expect(screen.getAllByText("Disconnected").length).toBeGreaterThan(0);
    expect(screen.getAllByText("connection refused").length).toBeGreaterThan(0);
  });

  it("distinguishes an unconfigured decoder from a broken one", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        status: "degraded",
        decoder: decoder({
          configured: false,
          state: "unconfigured",
          last_success: null,
          total_successes: 0,
          updates_ingested: 0,
        }),
      }),
    });
    renderApp("/health");

    // A first-run install is not an outage.
    expect(await screen.findAllByText("Not configured")).not.toHaveLength(0);
    expect(screen.queryByText("Disconnected")).not.toBeInTheDocument();
  });

  it("surfaces a failed integrity check and its rows", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        status: "down",
        database: database({
          status: "down",
          quick_check: {
            healthy: false,
            checked_at: "2026-08-31T13:00:00.000Z",
            error: null,
            rows: ["row 3 missing from index sightings_icao"],
          },
        }),
      }),
    });
    renderApp("/health");

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(
      screen.getByText("row 3 missing from index sightings_icao"),
    ).toBeInTheDocument();
  });

  it("says an integrity check has not run rather than claiming health", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        database: database({
          quick_check: {
            healthy: null,
            checked_at: null,
            error: null,
            rows: [],
          },
        }),
      }),
    });
    renderApp("/health");

    expect(await screen.findByText("Not yet checked")).toBeInTheDocument();
    expect(screen.getByText("Not yet run")).toBeInTheDocument();
  });

  it("shows a metadata import failure with its reason", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        status: "degraded",
        metadata: metadata({
          sources: [
            metadataSource({
              source: "faa",
              status: "failed",
              last_success_at: null,
              age_s: null,
              last_error: "download timed out",
            }),
          ],
          newest_success_at: null,
          age_s: null,
        }),
      }),
    });
    renderApp("/health");

    expect(await screen.findByText("download timed out")).toBeInTheDocument();
    expect(screen.getByText("No successful import yet")).toBeInTheDocument();
  });

  it("renders recent errors with their detail", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        recent_errors: {
          ingestion: [errorEntry()],
          database: [],
          enrichment: [],
          websocket: [],
          other: [],
        },
      }),
    });
    renderApp("/health");

    const [entry, ...rest] = await screen.findAllByTestId("health-error-entry");
    expect(rest).toHaveLength(0);
    expect(entry).toBeDefined();
    expect(within(entry!).getByText("decoder_poll_failed")).toBeInTheDocument();
    expect(
      within(entry!).getByText("url=http://decoder.invalid, attempt=3"),
    ).toBeInTheDocument();
  });

  it("reports an unreachable database without blanking the page", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        status: "down",
        database: database({
          status: "down",
          reachable: false,
          storage: {
            database_bytes: null,
            file_bytes: null,
            wal_bytes: null,
            reclaimable_bytes: null,
            reclaimable_ratio: null,
            disk_free_bytes: null,
            page_count: null,
            page_size: null,
          },
          row_counts: {
            aircraft: null,
            sightings: null,
            sighting_tracks: null,
            activity_events: null,
            alert_matches: null,
            aircraft_metadata: null,
            airports: null,
            receiver_metrics_raw: null,
          },
        }),
      }),
    });
    renderApp("/health");

    // The version card still renders — one broken subsystem must not cost
    // the user every other answer on the page.
    expect(await screen.findByText("0.9.2")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("explains itself when diagnostics cannot be loaded at all", async () => {
    installDiagnosticsApiMock({ status: 503 });
    renderApp("/health");

    expect(
      await screen.findByText(/Could not load diagnostics/),
    ).toBeInTheDocument();
  });
});

describe("HealthPage notification status", () => {
  it("reports the browser permission the backend cannot see", async () => {
    installDiagnosticsApiMock();
    renderApp("/health");

    const card = await screen.findByTestId("health-notification-permission");
    // jsdom has no Notification API, which is a real state users hit.
    expect(card).toHaveAttribute("data-permission", "unsupported");
  });

  it("shows delivered and suppressed counts from slice 040's store", async () => {
    useNotificationStore.getState().recordDelivered();
    useNotificationStore.getState().recordDelivered();
    useNotificationStore.getState().recordError("permission denied");

    installDiagnosticsApiMock();
    renderApp("/health");

    const card = await screen.findByTestId("health-notification-permission");
    expect(
      within(card).getByText("Delivered this session"),
    ).toBeInTheDocument();
    expect(within(card).getByText("2")).toBeInTheDocument();
    expect(
      screen.getByText(/Last delivery error: permission denied/),
    ).toBeInTheDocument();
  });

  it("never offers to request permission from the health page", async () => {
    // SECURITY §5: the ask must originate from the setup wizard or the
    // Notifications settings section, never from a read-only view.
    installDiagnosticsApiMock();
    renderApp("/health");

    await screen.findByTestId("health-notification-permission");
    expect(
      screen.queryByRole("button", { name: /enable notifications/i }),
    ).not.toBeInTheDocument();
  });
});
