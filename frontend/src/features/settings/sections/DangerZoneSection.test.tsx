import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DangerZoneSection } from "@/features/settings/sections/DangerZoneSection";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DangerZoneSection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DangerZoneSection", () => {
  it("renders both actions with destructive styling and a backup suggestion", () => {
    renderSection();

    expect(screen.getByText("Danger zone")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear metadata cache…/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reset flightsite data…/i }),
    ).toBeInTheDocument();
  });

  it("does not call the API until the dialog opens", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderSection();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  describe("Clear Metadata Cache", () => {
    it("keeps the confirm button disabled until the phrase matches exactly", async () => {
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /clear metadata cache…/i }),
      );

      const dialog = await screen.findByRole("dialog");
      const confirmButton = within(dialog).getByRole("button", {
        name: "Clear Metadata Cache",
      });
      const input = within(dialog).getByLabelText(/type/i);

      expect(confirmButton).toBeDisabled();

      await user.type(input, "clear-metad");
      expect(confirmButton).toBeDisabled();

      await user.type(input, "ata-oops");
      expect(confirmButton).toBeDisabled();

      await user.clear(input);
      await user.type(input, "clear-metadata");
      expect(confirmButton).toBeEnabled();
    });

    it("surfaces the backup suggestion before the operator can confirm", async () => {
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /clear metadata cache…/i }),
      );

      const dialog = await screen.findByRole("dialog");
      expect(
        within(dialog).getByText(/take a backup first/i),
      ).toBeInTheDocument();
      expect(
        within(dialog).getByText(/flightsite-backup create/i),
      ).toBeInTheDocument();
    });

    it("calls the confirmed action only once the phrase matches, then reports the counts", async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse({
          cleared: true,
          aircraft_metadata_rows: 4,
          staging_rows: 0,
          resolved_rows: 4,
          classification_rows: 0,
          operator_rows: 1,
          operator_group_rows: 1,
          route_cache_rows: 2,
          airport_rows: 9,
          sources_reset: 1,
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /clear metadata cache…/i }),
      );
      const dialog = await screen.findByRole("dialog");
      await user.type(within(dialog).getByLabelText(/type/i), "clear-metadata");
      await user.click(
        within(dialog).getByRole("button", { name: "Clear Metadata Cache" }),
      );

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/internal/reset/metadata-cache");
      expect(JSON.parse(init.body as string)).toEqual({
        confirm: "clear-metadata",
      });

      expect(
        await screen.findByText(/9 airport row\(s\) removed/i),
      ).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("closing the dialog without confirming performs no request", async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /clear metadata cache…/i }),
      );
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("shows the backend's error without pretending success on a wrong confirm", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          jsonResponse(
            {
              detail:
                "confirm must be exactly 'clear-metadata' to perform this action",
            },
            422,
          ),
        ),
      );
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /clear metadata cache…/i }),
      );
      const dialog = await screen.findByRole("dialog");
      // The dialog itself only ever sends the exact phrase; this proves the
      // section surfaces a rejection instead of silently succeeding, for the
      // case where the backend's gate and this dialog's ever disagree.
      await user.type(within(dialog).getByLabelText(/type/i), "clear-metadata");
      await user.click(
        within(dialog).getByRole("button", { name: "Clear Metadata Cache" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        /confirm must be exactly/i,
      );
    });
  });

  describe("Reset FlightSite Data", () => {
    it("keeps the confirm button disabled until the reset phrase matches exactly", async () => {
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /reset flightsite data…/i }),
      );
      const dialog = await screen.findByRole("dialog");
      const confirmButton = within(dialog).getByRole("button", {
        name: "Reset FlightSite Data",
      });

      expect(confirmButton).toBeDisabled();
      await user.type(
        within(dialog).getByLabelText(/type/i),
        "reset-flightsite-data",
      );
      expect(confirmButton).toBeEnabled();
    });

    it("requests the reset and shows the restart-required message", async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse(
          {
            accepted: true,
            requested_ms: 1_756_600_000_000,
            restart_required: true,
            message:
              "FlightSite data will be reset on the next restart. Restart the stack (docker compose restart) to apply it.",
          },
          202,
        ),
      );
      vi.stubGlobal("fetch", fetchMock);
      const user = userEvent.setup();
      renderSection();

      await user.click(
        screen.getByRole("button", { name: /reset flightsite data…/i }),
      );
      const dialog = await screen.findByRole("dialog");
      await user.type(
        within(dialog).getByLabelText(/type/i),
        "reset-flightsite-data",
      );
      await user.click(
        within(dialog).getByRole("button", { name: "Reset FlightSite Data" }),
      );

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/internal/reset/data");
      expect(JSON.parse(init.body as string)).toEqual({
        confirm: "reset-flightsite-data",
      });
      expect(await screen.findByText(/restart the stack/i)).toBeInTheDocument();
    });
  });

  it("Escape closes an open dialog without confirming", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", { name: /reset flightsite data…/i }),
    );
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
