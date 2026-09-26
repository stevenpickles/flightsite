import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FeedersSection } from "@/features/settings/sections/FeedersSection";
import type { FeedersConfig, FlightSiteConfig } from "@/lib/api/config";
import {
  defaultFeedersConfig,
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";

function renderSection(
  config: FlightSiteConfig = defaultFlightSiteConfig(),
  secretsSet: Record<string, boolean> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FeedersSection config={config} secretsSet={secretsSet} />
    </QueryClientProvider>,
  );
}

function configWithFeeders(feeders: Partial<FeedersConfig>): FlightSiteConfig {
  return defaultFlightSiteConfig({ feeders: defaultFeedersConfig(feeders) });
}

const RECEIVER_ENTRY = {
  name: "receiver",
  label: "Receiver (readsb)",
  kind: "readsb" as const,
  url: "http://host.docker.internal:8080/",
  web_url: "http://fermi.local:8080/",
};

const ADSBX_ENTRY = {
  name: "adsbx",
  label: "ADS-B Exchange",
  kind: "ultrafeeder" as const,
  url: "http://host.docker.internal:8080/",
  host: "feed.adsbexchange.com",
  mlat_port: 31090,
  beast_port: 30004,
  container: "ultrafeeder",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FeedersSection", () => {
  it("renders the poll interval, docker socket helper text, and existing entries", () => {
    installConfigApiMock();
    renderSection(
      configWithFeeders({
        poll_interval_s: 20,
        docker_socket: "/var/run/docker.sock",
        entries: [RECEIVER_ENTRY],
        local_pages: [{ label: "tar1090", url: "http://fermi.local:8080/" }],
      }),
    );

    expect(screen.getByLabelText(/poll interval/i)).toHaveValue("20");
    expect(screen.getByLabelText(/docker socket path/i)).toHaveValue(
      "/var/run/docker.sock",
    );
    expect(
      screen.getByText(/requires the socket mounted into the backend/i),
    ).toBeInTheDocument();

    const rows = screen.getAllByTestId("feeders-entry-row");
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByLabelText(/name/i)).toHaveValue("receiver");
    expect(within(rows[0]!).getByLabelText(/label/i)).toHaveValue(
      "Receiver (readsb)",
    );

    expect(screen.getByLabelText(/local page 1 label/i)).toHaveValue("tar1090");
  });

  it("carries no restart-required badge — feeders apply on save", () => {
    installConfigApiMock();
    const { container } = renderSection();

    expect(screen.queryByText(/applies on next restart/i)).toBeNull();
    expect(container).not.toHaveTextContent(/restart/i);
  });

  it("blocks Save on an out-of-range poll interval", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(/poll interval/i));
    await user.type(screen.getByLabelText(/poll interval/i), "3");

    expect(
      screen.getByText(/whole number of seconds between 5 and 120/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("blocks Save on a docker socket path that isn't absolute", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.type(
      screen.getByLabelText(/docker socket path/i),
      "var/run/docker.sock",
    );

    expect(screen.getByText(/enter an absolute path/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("adds a feeder row and requires a name, label and URL for its kind", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /add feeder/i }));
    expect(screen.getAllByTestId("feeders-entry-row")).toHaveLength(1);

    // A blank new row is dirty (an empty entry differs from no entries) and
    // its required fields are blank, so Save is blocked until it is filled
    // in or removed.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(screen.getByText(/name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/label is required/i)).toBeInTheDocument();
  });

  it("rejects a slug-shaped name that isn't lowercase/hyphenated", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(configWithFeeders({ entries: [RECEIVER_ENTRY] }));

    const nameInput = screen.getByLabelText(/feeder 1 name/i);
    await user.clear(nameInput);
    await user.type(nameInput, "My Feeder!");

    expect(
      screen.getByText(/lowercase letters, digits, hyphens or underscores/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("rejects two entries sharing the same name", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({ entries: [RECEIVER_ENTRY, ADSBX_ENTRY] }),
    );

    const secondName = screen.getByLabelText(/feeder 2 name/i);
    await user.clear(secondName);
    await user.type(secondName, "receiver");

    expect(screen.getAllByText(/name must be unique/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("requires an http(s) URL and rejects a bare host", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(configWithFeeders({ entries: [RECEIVER_ENTRY] }));

    const urlInput = screen.getByLabelText(/feeder 1 url/i);
    await user.clear(urlInput);
    await user.type(urlInput, "fermi.local:8080");

    expect(
      screen.getByText(/starting with http:\/\/ or https:\/\//i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("shows kind-dependent fields only for the relevant kind", () => {
    installConfigApiMock();
    renderSection(configWithFeeders({ entries: [ADSBX_ENTRY] }));

    expect(screen.getByLabelText(/feeder 1 host/i)).toHaveValue(
      "feed.adsbexchange.com",
    );
    expect(screen.getByLabelText(/feeder 1 mlat port/i)).toHaveValue("31090");
    expect(screen.getByLabelText(/feeder 1 beast port/i)).toHaveValue("30004");
    expect(screen.getByLabelText(/feeder 1 container/i)).toHaveValue(
      "ultrafeeder",
    );
  });

  it("hides host/port/container fields for a kind that doesn't use them", () => {
    installConfigApiMock();
    renderSection(configWithFeeders({ entries: [RECEIVER_ENTRY] }));

    expect(screen.queryByLabelText(/feeder 1 host/i)).toBeNull();
    expect(screen.queryByLabelText(/feeder 1 mlat port/i)).toBeNull();
    expect(screen.queryByLabelText(/feeder 1 container/i)).toBeNull();
    expect(screen.getByLabelText(/feeder 1 url/i)).toHaveValue(
      "http://host.docker.internal:8080/",
    );
  });

  it("removes a feeder row", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({ entries: [RECEIVER_ENTRY, ADSBX_ENTRY] }),
    );

    expect(screen.getAllByTestId("feeders-entry-row")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: /remove feeder 1/i }));
    expect(screen.getAllByTestId("feeders-entry-row")).toHaveLength(1);
    expect(screen.getByLabelText(/feeder 1 name/i)).toHaveValue("adsbx");
  });

  it("reorders feeder rows with the move controls", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({ entries: [RECEIVER_ENTRY, ADSBX_ENTRY] }),
    );

    expect(screen.getByLabelText(/move feeder 1 up/i)).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: /move feeder 1 down/i }),
    );

    expect(screen.getByLabelText(/feeder 1 name/i)).toHaveValue("adsbx");
    expect(screen.getByLabelText(/feeder 2 name/i)).toHaveValue("receiver");
  });

  it("the stats URL field starts blank with the configured placeholder", () => {
    installConfigApiMock();
    renderSection(configWithFeeders({ entries: [RECEIVER_ENTRY] }), {
      "feeders.stats_urls.receiver": true,
    });

    expect(screen.getByLabelText(/feeder 1 stats url/i)).toHaveValue("");
    expect(
      screen.getByPlaceholderText(/configured — leave blank to keep/i),
    ).toBeInTheDocument();
  });

  it("shows 'not configured' for a stats URL that isn't stored", () => {
    installConfigApiMock();
    renderSection(configWithFeeders({ entries: [RECEIVER_ENTRY] }));

    expect(
      screen.getByPlaceholderText(/^not configured$/i),
    ).toBeInTheDocument();
  });

  it("saves a typed stats URL for one row without touching another row's", async () => {
    const { fetchMock } = installConfigApiMock({
      config: configWithFeeders({ entries: [RECEIVER_ENTRY, ADSBX_ENTRY] }),
      secretsSet: { "feeders.stats_urls.adsbx": true },
    });
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({ entries: [RECEIVER_ENTRY, ADSBX_ENTRY] }),
      { "feeders.stats_urls.adsbx": true },
    );

    await user.type(
      screen.getByLabelText(/feeder 1 stats url/i),
      "https://example.com/receiver-stats",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as {
      feeders: { stats_urls?: Record<string, string | null> };
    };
    expect(body.feeders.stats_urls).toEqual({
      receiver: "https://example.com/receiver-stats",
    });
  });

  it("loads the example config into the draft without saving", async () => {
    installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", {
        name: /load the example for a pi with ultrafeeder/i,
      }),
    );

    expect(screen.getAllByTestId("feeders-entry-row")).toHaveLength(6);
    expect(screen.getByLabelText(/feeder 1 name/i)).toHaveValue("receiver");
    expect(screen.getByLabelText(/local page 1 label/i)).toHaveValue("tar1090");
    // Not saved yet — no PUT has gone out.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });

  it("round-trips an added local page: add, save, reload", async () => {
    const { fetchMock, getCurrentConfig } = installConfigApiMock();
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /add local page/i }));
    await user.type(screen.getByLabelText(/local page 1 label/i), "tar1090");
    await user.type(
      screen.getByLabelText(/local page 1 url/i),
      "http://fermi.local:8080/",
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    expect(getCurrentConfig().config.feeders.local_pages).toEqual([
      { label: "tar1090", url: "http://fermi.local:8080/" },
    ]);

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body)) as {
      feeders: { local_pages: unknown[] };
    };
    expect(body.feeders.local_pages).toEqual([
      { label: "tar1090", url: "http://fermi.local:8080/" },
    ]);
  });

  it("removes a local page and saves the shorter list", async () => {
    const { getCurrentConfig } = installConfigApiMock({
      config: configWithFeeders({
        local_pages: [{ label: "tar1090", url: "http://fermi.local:8080/" }],
      }),
    });
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({
        local_pages: [{ label: "tar1090", url: "http://fermi.local:8080/" }],
      }),
    );

    await user.click(
      screen.getByRole("button", { name: /remove local page 1/i }),
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    expect(getCurrentConfig().config.feeders.local_pages).toEqual([]);
  });

  it("shows a server-side field error against the row and field it names", async () => {
    installConfigApiMock();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ["feeders", "entries", 2, "url"],
                msg: "That host could not be resolved.",
                type: "value_error",
              },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSection(
      configWithFeeders({
        entries: [
          RECEIVER_ENTRY,
          { ...ADSBX_ENTRY, name: "aerodatabox" },
          { ...RECEIVER_ENTRY, name: "fr24" },
        ],
      }),
    );

    // The section starts clean (draft === baseline), so Save is disabled
    // until something is actually edited — a harmless reorder here, which
    // leaves every field's own validity untouched.
    await user.click(
      screen.getByRole("button", { name: /move feeder 1 down/i }),
    );
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    const rows = screen.getAllByTestId("feeders-entry-row");
    expect(
      await within(rows[2]!).findByText(/that host could not be resolved/i),
    ).toBeInTheDocument();
    expect(within(rows[0]!).queryByText(/could not be resolved/i)).toBeNull();
    // A server rejection never disables Save — it must stay retryable.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
  });
});
