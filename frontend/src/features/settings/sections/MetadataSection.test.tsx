import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { formatReceiverLocalTime } from "@/features/aircraft-detail/lib/format";
import { MetadataSection } from "@/features/settings/sections/MetadataSection";
import { installMetadataApiMock, metadataSource } from "@/test/metadataApiMock";

const TIMEZONE = "UTC";
//: A fixed instant far enough in the past that its relative age never
// resolves to something like "just now" no matter when the suite runs.
const OK_SUCCESS_MS = Date.UTC(2020, 0, 15, 8, 30, 0);
const EXPECTED_LOCAL_TIME = formatReceiverLocalTime(
  new Date(OK_SUCCESS_MS).toISOString(),
  TIMEZONE,
);

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MetadataSection timezone={TIMEZONE} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MetadataSection", () => {
  it("renders a never-run source and an overall 'never' age line", async () => {
    installMetadataApiMock({
      statusSequence: [{ sources: [metadataSource({ name: "mictronics" })] }],
    });
    renderSection();

    expect(await screen.findByText("Mictronics")).toBeInTheDocument();
    expect(screen.getByText("Never run")).toBeInTheDocument();
    expect(screen.getByText("Never updated.")).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("renders a successful source with version, row count and the age line", async () => {
    installMetadataApiMock({
      statusSequence: [
        {
          sources: [
            metadataSource({
              name: "mictronics",
              status: "ok",
              last_success_ms: OK_SUCCESS_MS,
              dataset_version: "2026-08-01",
              row_count: 42_000,
            }),
          ],
        },
      ],
    });
    renderSection();

    expect(await screen.findByText("Up to date")).toBeInTheDocument();
    expect(
      screen.getByText("Version 2026-08-01 · 42,000 aircraft"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(`Last updated ${EXPECTED_LOCAL_TIME}`)),
    ).toBeInTheDocument();
    // The overall age line uses the same successful timestamp.
    expect(screen.getByText(/metadata last updated:/i)).toHaveTextContent(
      EXPECTED_LOCAL_TIME,
    );
  });

  it("renders a failing source with its error and a data-safety reassurance, independent of a healthy source", async () => {
    installMetadataApiMock({
      statusSequence: [
        {
          sources: [
            metadataSource({
              name: "mictronics",
              status: "ok",
              last_success_ms: OK_SUCCESS_MS,
              dataset_version: "2026-08-01",
              row_count: 42_000,
            }),
            metadataSource({
              name: "faa",
              status: "failed",
              last_error: "upstream unreachable",
            }),
          ],
        },
      ],
    });
    renderSection();

    // The failing source's own card:
    expect(await screen.findByText("upstream unreachable")).toBeInTheDocument();
    expect(
      screen.getByText(/Previous FAA data is unaffected/i),
    ).toBeInTheDocument();

    // The healthy source is unobscured — its own success still renders in full.
    expect(screen.getByText("Up to date")).toBeInTheDocument();
    expect(
      screen.getByText("Version 2026-08-01 · 42,000 aircraft"),
    ).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows a load error without crashing the section", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );
    renderSection();

    expect(
      await screen.findByText(/could not load metadata source status/i),
    ).toBeInTheDocument();
  });

  it("triggers an update and reflects the in-progress state from the very next poll", async () => {
    installMetadataApiMock({
      statusSequence: [
        { sources: [metadataSource({ name: "mictronics", status: "ok" })] },
        {
          sources: [metadataSource({ name: "mictronics", status: "running" })],
        },
      ],
      triggerResult: {
        started: true,
        already_running: false,
        started_ms: 1_756_600_000_000,
      },
    });
    const user = userEvent.setup();
    renderSection();

    await screen.findByText("Up to date");
    await user.click(
      screen.getByRole("button", { name: /update aircraft metadata/i }),
    );

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /updating/i })).toBeDisabled();
  });

  it("polls until the run settles, then stops showing the running state", async () => {
    installMetadataApiMock({
      statusSequence: [
        {
          sources: [
            metadataSource({ name: "mictronics", status: "never-run" }),
          ],
        },
        {
          sources: [metadataSource({ name: "mictronics", status: "running" })],
        },
        {
          sources: [
            metadataSource({
              name: "mictronics",
              status: "ok",
              last_success_ms: OK_SUCCESS_MS,
              dataset_version: "2026-08-01",
              row_count: 10,
            }),
          ],
        },
      ],
    });
    const user = userEvent.setup();
    renderSection();

    await screen.findByText("Never run");
    await user.click(
      screen.getByRole("button", { name: /update aircraft metadata/i }),
    );

    await screen.findByText("Running");
    // The next scheduled poll (METADATA_POLL_INTERVAL_MS) picks up the
    // settled state — no further click or manual refetch involved.
    expect(
      await screen.findByText("Up to date", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /update aircraft metadata/i }),
    ).toBeEnabled();
  });

  it("reports a coalesced trigger without claiming a fresh run started", async () => {
    // This tab still shows "ok" (it has not polled since another tab, or a
    // very close double-click, started a run) — the button is enabled, and
    // the backend is what tells this trigger it coalesced.
    installMetadataApiMock({
      statusSequence: [
        { sources: [metadataSource({ name: "mictronics", status: "ok" })] },
      ],
      triggerResult: {
        started: false,
        already_running: true,
        started_ms: 1_756_600_000_000,
      },
    });
    const user = userEvent.setup();
    renderSection();

    await screen.findByText("Up to date");
    await user.click(
      screen.getByRole("button", { name: /update aircraft metadata/i }),
    );

    expect(
      await screen.findByText(/an update was already running/i),
    ).toBeInTheDocument();
  });

  it("shows a trigger error without losing the previously loaded status", async () => {
    vi.stubGlobal("fetch", (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      if (url === "/api/internal/metadata/status" && method === "GET") {
        return new Response(
          JSON.stringify({ sources: [metadataSource({ name: "mictronics" })] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/internal/metadata/update" && method === "POST") {
        return new Response(JSON.stringify({ detail: "boom" }), {
          status: 500,
        });
      }
      throw new Error(`Unhandled fetch: ${method} ${url}`);
    }) as typeof fetch);
    const user = userEvent.setup();
    renderSection();

    await screen.findByText("Never run");
    await user.click(
      screen.getByRole("button", { name: /update aircraft metadata/i }),
    );

    expect(await screen.findByText("boom")).toBeInTheDocument();
    // The section keeps showing the status it already had.
    expect(screen.getByText("Never run")).toBeInTheDocument();
  });
});
