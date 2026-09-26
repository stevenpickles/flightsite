/**
 * Static metadata for the seven feeder kinds (`docs/design/077-feeders-page.md`
 * "Kinds") that the entries editor and its validation need but that isn't
 * itself part of the config document: a human label per kind, and which of
 * the kind-dependent field groups (`url` / `container` / `host` +
 * `mlat_port` + `beast_port` / `web_url`) a row of that kind shows.
 *
 * **Assumption** (work package D; no backend contract to check this
 * against): the design record's example config gives `url`+`web_url` to
 * `readsb`/`piaware`/`fr24`, `url`+`host`+`mlat_port`+`beast_port`+
 * `container` to `ultrafeeder`, and bare `container` to `opensky_logs` — it
 * never shows a `docker_health` or `link_only` row, so their field sets
 * below are inferred from their one-line descriptions ("backstop, socket
 * only" and a plain link respectively) rather than confirmed against a
 * fixture. `web_url` is treated as always optional and available on every
 * kind (it is just the card's "Open" link, orthogonal to how — or whether —
 * status is probed), which is a superset of what the example shows for
 * `ultrafeeder`/`opensky_logs` but never a value the backend would reject
 * as unknown, since it is a plain top-level entry field for every kind in
 * the design record's schema.
 */
import type { FeederEntryConfig, FeederKind } from "@/lib/api/config";
import type { FeederEntryDraft } from "@/features/settings/types";

export const FEEDER_KINDS: readonly FeederKind[] = [
  "readsb",
  "piaware",
  "fr24",
  "ultrafeeder",
  "opensky_logs",
  "docker_health",
  "link_only",
];

export const FEEDER_KIND_LABELS: Record<FeederKind, string> = {
  readsb: "Receiver (readsb / ultrafeeder)",
  piaware: "FlightAware (piaware)",
  fr24: "FlightRadar24",
  ultrafeeder: "Ultrafeeder MLAT peer (ADS-B Exchange, AeroDataBox, …)",
  opensky_logs: "OpenSky Network (logs only)",
  docker_health: "Docker container health (backstop)",
  link_only: "Link only (no status probe)",
};

interface FeederKindFields {
  url: boolean;
  container: boolean;
  hostPorts: boolean;
}

/** Which kind-dependent field groups a row of this kind shows, beyond the
 * always-present `web_url` (see the module doc for why that one is not
 * gated). */
const KIND_FIELDS: Record<FeederKind, FeederKindFields> = {
  readsb: { url: true, container: false, hostPorts: false },
  piaware: { url: true, container: false, hostPorts: false },
  fr24: { url: true, container: false, hostPorts: false },
  ultrafeeder: { url: true, container: true, hostPorts: true },
  opensky_logs: { url: false, container: true, hostPorts: false },
  docker_health: { url: false, container: true, hostPorts: false },
  link_only: { url: false, container: false, hostPorts: false },
};

export function feederKindFields(kind: FeederKind): FeederKindFields {
  return KIND_FIELDS[kind];
}

/** A fresh, blank entry row — the "Add feeder" starting point. */
export function emptyFeederEntryDraft(): FeederEntryDraft {
  return {
    name: "",
    label: "",
    kind: "link_only",
    url: "",
    container: "",
    host: "",
    mlatPort: "",
    beastPort: "",
    webUrl: "",
    statsUrlInput: "",
    statsUrlTouched: false,
    statsUrlStored: false,
  };
}

/** A fresh, blank local-page row. */
export function emptyLocalPageDraft(): { label: string; url: string } {
  return { label: "", url: "" };
}

/**
 * The example fermi.local configuration from the design record's "Config"
 * section, verbatim — the six entries and four local pages a Pi running
 * ultrafeeder + piaware + fr24 + opensky would have. Loaded into the draft
 * by the "Load the example" button, never saved automatically.
 */
export const FEEDERS_EXAMPLE_ENTRIES: readonly FeederEntryConfig[] = [
  {
    name: "receiver",
    label: "Receiver (readsb)",
    kind: "readsb",
    url: "http://host.docker.internal:8080/",
    web_url: "http://fermi.local:8080/",
  },
  {
    name: "flightaware",
    label: "FlightAware",
    kind: "piaware",
    url: "http://host.docker.internal:8081/status.json",
    web_url: "http://fermi.local:8081/",
  },
  {
    name: "fr24",
    label: "FlightRadar24",
    kind: "fr24",
    url: "http://host.docker.internal:8754/monitor.json",
    web_url: "http://fermi.local:8754/",
  },
  {
    name: "adsbx",
    label: "ADS-B Exchange",
    kind: "ultrafeeder",
    url: "http://host.docker.internal:8080/",
    host: "feed.adsbexchange.com",
    mlat_port: 31090,
    beast_port: 30004,
    container: "ultrafeeder",
  },
  {
    name: "aerodatabox",
    label: "AeroDataBox",
    kind: "ultrafeeder",
    url: "http://host.docker.internal:8080/",
    host: "feed.aerodatabox.com",
    mlat_port: 31090,
    beast_port: 30004,
    container: "ultrafeeder",
  },
  {
    name: "opensky",
    label: "OpenSky Network",
    kind: "opensky_logs",
    container: "opensky",
  },
];

export const FEEDERS_EXAMPLE_LOCAL_PAGES: readonly {
  label: string;
  url: string;
}[] = [
  { label: "tar1090", url: "http://fermi.local:8080/" },
  { label: "graphs1090", url: "http://fermi.local:8080/graphs1090/" },
  { label: "SkyAware", url: "http://fermi.local:8081/" },
  { label: "FR24 feeder", url: "http://fermi.local:8754/" },
];
