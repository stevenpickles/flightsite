import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNotificationStore } from "@/features/notifications/store/useNotificationStore";
import { defaultFlightSiteConfig } from "@/test/configApiMock";
import {
  database,
  decoder,
  diagnostics,
  errorEntry,
  installDiagnosticsApiMock,
  liveEvents,
  liveEventSubscriber,
  metadata,
  metadataSource,
} from "@/test/diagnosticsApiMock";
import { renderApp } from "@/test/test-utils";
import { DIAGNOSTICS_POLL_MS } from "@/lib/api/diagnostics";

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
      within(summary).getByText("0 clients shed since start-up"),
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

  it("puts the enrichment budget and cache counters on the page", async () => {
    installDiagnosticsApiMock();
    renderApp("/health");

    const card = await screen.findByRole("region", {
      name: "Route enrichment",
    });
    expect(within(card).getByText("12 / 100 used")).toBeInTheDocument();
    expect(within(card).getByText("88 left today")).toBeInTheDocument();
    expect(within(card).getByText("Routes learned")).toBeInTheDocument();
  });

  it("names the consumer that shed live events, not the WebSocket", async () => {
    // Issue #185: the owner's Pi showed 18,061 drops beside "WebSocket
    // clients" while the persistence queue had shed every one of them.
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        live_events: liveEvents({
          dropped: 18_061,
          subscribers: [
            liveEventSubscriber({
              name: "persistence",
              dropped: 18_061,
              pending: 4096,
              overflowed: true,
            }),
            liveEventSubscriber({ name: "websocket" }),
          ],
        }),
      }),
    });
    renderApp("/health");

    const card = await screen.findByRole("region", { name: "Live events" });
    const persistence = within(card).getByText("persistence").closest("div");
    const websocket = within(card).getByText("websocket").closest("div");

    expect(persistence).not.toBeNull();
    expect(websocket).not.toBeNull();
    expect(within(persistence!).getByText("18,061 shed")).toBeInTheDocument();
    expect(
      within(persistence!).getByText("4,096 / 4,096 queued"),
    ).toBeInTheDocument();
    // SPEC §80: the marker is a word and an icon, never colour alone.
    expect(within(persistence!).getByText("Resyncing")).toBeInTheDocument();
    expect(within(websocket!).getByText("0 shed")).toBeInTheDocument();
    expect(within(websocket!).queryByText("Resyncing")).toBeNull();

    // And the WebSocket tile no longer wears the process-wide total.
    const summary = screen.getByRole("group", { name: "Health summary" });
    expect(within(summary).queryByText(/18,061/)).toBeNull();
    expect(
      within(summary).getByText("0 clients shed since start-up"),
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

  it("explains a VACUUM blocked on free space, with both numbers", async () => {
    // Issue #116: the guard needs free space of twice the database, so on a
    // large history it can be refused permanently. The page has to say so, and
    // has to give the gap — "blocked" alone reads like a transient state.
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        database: database({
          maintenance: {
            cycles: 42,
            last_cycle_at: "2026-08-31T13:00:00.000Z",
            healthy: true,
            running: true,
            jobs: {},
            vacuum_refusal: {
              reason: "insufficient_free_space",
              required_free_bytes: 9_000_000_000,
              available_free_bytes: 3_100_000_000,
            },
          },
        }),
      }),
    });
    renderApp("/health");

    expect(
      await screen.findByText("Blocked — not enough free space"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Needs 8\.4 GB free, has 2\.9 GB/),
    ).toBeInTheDocument();
    // A refusal is the policy working, so it must not read as a failure.
    expect(screen.getByText("Running cleanly")).toBeInTheDocument();
  });

  it("says nothing about compaction when no VACUUM has been refused", async () => {
    installDiagnosticsApiMock();
    renderApp("/health");

    await screen.findByRole("group", { name: "Health summary" });
    expect(screen.queryByText("Compaction")).not.toBeInTheDocument();
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
    // R4-14: the same source reads as the same name Settings uses, not the
    // raw internal key.
    expect(screen.getByText("FAA")).toBeInTheDocument();
    expect(screen.queryByText("faa")).toBeNull();
  });

  it("names sources and their row noun the same way Settings does, and links there directly (R4-14)", async () => {
    installDiagnosticsApiMock({
      diagnostics: diagnostics({
        metadata: metadata({
          sources: [
            metadataSource({
              source: "airports",
              status: "ok",
              row_count: 74_112,
            }),
          ],
        }),
      }),
    });
    renderApp("/health");

    const card = await screen.findByRole("region", {
      name: "Metadata datasets",
    });
    expect(within(card).getByText("Airports")).toBeInTheDocument();
    expect(within(card).getByText(/74,112 airports/)).toBeInTheDocument();
    expect(
      within(card).getByRole("link", { name: /update metadata in settings/i }),
    ).toHaveAttribute("href", "/settings#settings-metadata");
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

describe("HealthPage R4-04: a failing poll keeps the last good payload", () => {
  function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it(
    "keeps the cards on screen and shows a stale banner instead of blanking the page",
    async () => {
      let diagnosticsCalls = 0;
      const fetchMock = vi.fn(
        async (input: RequestInfo | URL, init?: RequestInit) => {
          const raw = typeof input === "string" ? input : input.toString();
          const method = (init?.method ?? "GET").toUpperCase();
          const url = new URL(raw, "http://localhost");

          if (url.pathname === "/api/internal/config" && method === "GET") {
            return jsonResponse({
              first_run: false,
              config: defaultFlightSiteConfig(),
              secrets_set: {},
            });
          }
          if (url.pathname === "/api/v1/diagnostics" && method === "GET") {
            diagnosticsCalls += 1;
            if (diagnosticsCalls === 1) {
              return jsonResponse(diagnostics());
            }
            // Every poll after the first fails — a decoder unplugged, a
            // reverse proxy blip, anything that outlives one 10s cycle.
            return jsonResponse(
              { error: { code: "unavailable", message: "Backend is down" } },
              503,
            );
          }
          throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
        },
      );
      vi.stubGlobal("fetch", fetchMock);
      const user = userEvent.setup();

      renderApp("/health");

      await screen.findByText("Healthy");

      // The next scheduled poll (DIAGNOSTICS_POLL_MS) fails — the page must
      // not discard the cards it already has.
      await screen.findByText(/refreshing failed/i, undefined, {
        timeout: DIAGNOSTICS_POLL_MS + 5000,
      });
      const banner = screen.getByRole("alert");
      expect(
        within(banner).getByRole("button", { name: /retry/i }),
      ).toBeInTheDocument();
      expect(screen.getByText("Healthy")).toBeInTheDocument();
      expect(
        screen.getByRole("group", { name: "Health summary" }),
      ).toBeInTheDocument();

      // Retry is offered — and using it does not itself throw or blank
      // the page even while still failing.
      await user.click(within(banner).getByRole("button", { name: /retry/i }));
      expect(screen.getByText("Healthy")).toBeInTheDocument();
    },
    DIAGNOSTICS_POLL_MS + 10_000,
  );
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
