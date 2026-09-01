import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { SetupWizardPage } from "@/features/setup/SetupWizardPage";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";
import { resetMapLibreMock } from "@/test/maplibreGlMock";
import { installNotificationMock } from "@/test/notificationMock";

function renderSetupWizardPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/setup"]}>
        <Routes>
          <Route path="/setup" element={<SetupWizardPage />} />
          <Route path="/" element={<div>Live Map Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetMapLibreMock();
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SetupWizardPage", () => {
  it("shows a loading state, then the welcome step, once the config loads", async () => {
    installConfigApiMock({ firstRun: true });
    renderSetupWizardPage();

    expect(screen.getByText(/loading configuration/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/welcome to flightsite/i),
    ).toBeInTheDocument();
  });

  it("shows a retry affordance when the initial config load fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );
    const user = userEvent.setup();
    renderSetupWizardPage();

    expect(
      await screen.findByText(/could not load the current configuration/i),
    ).toBeInTheDocument();
    const { fetchMock } = installConfigApiMock({ firstRun: true });
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(fetchMock).toHaveBeenCalled();
    expect(
      await screen.findByText(/welcome to flightsite/i),
    ).toBeInTheDocument();
  });

  it("prefills from the current config in edit mode (non-first-run)", async () => {
    installConfigApiMock({
      firstRun: false,
      config: defaultFlightSiteConfig({
        location: {
          latitude: 47.6,
          longitude: -122.3,
          site_name: "Home Roof",
          antenna_height_ft: null,
        },
      }),
    });
    renderSetupWizardPage();

    expect(await screen.findByText(/update your setup/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/site name/i)).toHaveValue("Home Roof");
    // Already valid — Next is immediately enabled without any edits.
    expect(screen.getByRole("button", { name: /^next$/i })).toBeEnabled();
  });

  it("completes the full wizard, saves once, and lands on the Live Map", async () => {
    const { fetchMock } = installConfigApiMock({ firstRun: true });
    const user = userEvent.setup();
    renderSetupWizardPage();

    // (a) Welcome
    await screen.findByText(/welcome to flightsite/i);
    await user.type(screen.getByLabelText(/site name/i), "Home Roof Antenna");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (b) Location
    await screen.findByText(/receiver location/i);
    await user.type(screen.getByLabelText(/latitude/i), "47.6");
    await user.type(screen.getByLabelText(/longitude/i), "-122.3");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (c) Decoder — explicitly skip the connection test.
    await screen.findByText(/decoder endpoint/i);
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /skip test/i }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (d) Units & timezone — defaults are already valid.
    await screen.findByText(/^units$/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (e) Notifications — defaults are valid.
    await screen.findByRole("heading", { name: /browser notifications/i });
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (f) Metadata — optional, skip.
    await screen.findByText(/metadata & enrichment/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (g) Alerts — keep the defaults.
    await screen.findByText(/alert templates/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // (h) Review & finish.
    await screen.findByRole("heading", { name: /^review$/i });
    expect(screen.getByText("Home Roof Antenna")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /finish setup/i }));

    expect(await screen.findByText("Live Map Page")).toBeInTheDocument();

    const putCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(putCalls).toHaveLength(1);
    const [, putInit] = putCalls[0] as [string, RequestInit];
    const body = JSON.parse(String(putInit.body));
    expect(body.location).toEqual({
      site_name: "Home Roof Antenna",
      latitude: 47.6,
      longitude: -122.3,
      antenna_height_ft: null,
    });

    // The map immediately centers on the configured site (slice-013
    // placeholder replaced) rather than the dev fallback.
    await waitFor(() => {
      expect(useMapConfigStore.getState().config.receiver).toEqual({
        lat: 47.6,
        lon: -122.3,
        label: "Home Roof Antenna",
      });
    });
  });

  it("lets the user revisit an already-completed step from the progress indicator", async () => {
    installConfigApiMock({ firstRun: true });
    const user = userEvent.setup();
    renderSetupWizardPage();

    await screen.findByText(/welcome to flightsite/i);
    await user.type(screen.getByLabelText(/site name/i), "Home");
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await screen.findByText(/receiver location/i);

    await user.click(screen.getByRole("button", { name: "Welcome" }));
    expect(
      await screen.findByText(/welcome to flightsite/i),
    ).toBeInTheDocument();

    // The not-yet-reached "Review" step stays disabled.
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
  });

  /**
   * Walks the wizard from Welcome to the Finish click, optionally switching
   * the notification preference off on the way past step (e).
   */
  async function completeWizard(
    user: ReturnType<typeof userEvent.setup>,
    { wantsNotifications }: { wantsNotifications: boolean },
  ): Promise<void> {
    await screen.findByText(/welcome to flightsite/i);
    await user.type(screen.getByLabelText(/site name/i), "Home");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/receiver location/i);
    await user.type(screen.getByLabelText(/latitude/i), "47.6");
    await user.type(screen.getByLabelText(/longitude/i), "-122.3");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/decoder endpoint/i);
    await user.click(screen.getByRole("button", { name: /skip test/i }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/^units$/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByRole("heading", { name: /browser notifications/i });
    if (!wantsNotifications) {
      await user.click(
        screen.getByRole("checkbox", { name: /enable browser notifications/i }),
      );
    }
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/metadata & enrichment/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/alert templates/i);
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByRole("heading", { name: /^review$/i });
    await user.click(screen.getByRole("button", { name: /finish setup/i }));
  }

  describe("notification permission (slice 040)", () => {
    it("never asks the browser while the wizard is merely open", async () => {
      // `docs/SECURITY.md` §5: requested only after the user opts in, never
      // unprompted — walking up to the notifications step is not an opt-in.
      installConfigApiMock({ firstRun: true });
      const api = installNotificationMock({ permission: "default" });
      const user = userEvent.setup();
      renderSetupWizardPage();

      await screen.findByText(/welcome to flightsite/i);
      await user.type(screen.getByLabelText(/site name/i), "Home");
      await user.click(screen.getByRole("button", { name: /^next$/i }));

      expect(api.requestPermission).not.toHaveBeenCalled();
    });

    it("asks once on Finish when the user opted in", async () => {
      installConfigApiMock({ firstRun: true });
      const api = installNotificationMock({
        permission: "default",
        requestResult: "granted",
      });
      const user = userEvent.setup();
      renderSetupWizardPage();

      await completeWizard(user, { wantsNotifications: true });

      expect(await screen.findByText("Live Map Page")).toBeInTheDocument();
      expect(api.requestPermission).toHaveBeenCalledTimes(1);
    });

    it("does not ask when the user turned notifications off", async () => {
      installConfigApiMock({ firstRun: true });
      const api = installNotificationMock({ permission: "default" });
      const user = userEvent.setup();
      renderSetupWizardPage();

      await completeWizard(user, { wantsNotifications: false });

      expect(await screen.findByText("Live Map Page")).toBeInTheDocument();
      expect(api.requestPermission).not.toHaveBeenCalled();
    });

    it("finishes setup even where the browser has no Notification API", async () => {
      vi.stubGlobal("Notification", undefined);
      installConfigApiMock({ firstRun: true });
      const user = userEvent.setup();
      renderSetupWizardPage();

      await completeWizard(user, { wantsNotifications: true });

      expect(await screen.findByText("Live Map Page")).toBeInTheDocument();
    });
  });
});
