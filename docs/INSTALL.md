# Installing FlightSite

FlightSite runs as two Docker containers — a Python backend and an nginx frontend —
managed by a single `compose.yaml`. This guide takes a bare Raspberry Pi 4 or generic
Linux host to a working install.

Read [§2 Preflight](#2-preflight-checks) before you start. Two of those checks take
thirty seconds and between them account for most first-install failures.

- [1. What you need](#1-what-you-need)
- [2. Preflight checks](#2-preflight-checks)
- [3. Install Docker](#3-install-docker)
- [4. Create the data directory](#4-create-the-data-directory)
- [5. Get FlightSite and start it](#5-get-flightsite-and-start-it)
- [6. First-run setup](#6-first-run-setup)
- [7. Verify the install](#7-verify-the-install)
- [8. Upgrading](#8-upgrading)
- [9. Troubleshooting](#9-troubleshooting)

---

## 1. What you need

| | Requirement |
|---|---|
| **Host** | Raspberry Pi 4 (4 GB or better) or any x86-64 Linux box |
| **OS** | A **64-bit** OS. Raspberry Pi OS (64-bit), Debian 12+, or Ubuntu 22.04+ |
| **Disk** | 8 GB free to start. The database grows with traffic — see [PERFORMANCE.md §7](PERFORMANCE.md) |
| **Docker** | Docker Engine 24+ with the Compose v2 plugin |
| **Decoder** | A running ADS-B decoder that serves `aircraft.json` over HTTP — readsb, dump1090-fa, or a tar1090 install |

FlightSite does **not** talk to an SDR dongle directly. It polls the JSON document
your existing decoder already publishes, so the decoder keeps working exactly as it
does today and FlightSite is purely additive. The decoder may run on the same host or
another machine on your LAN.

FlightSite has no login and is designed for a **trusted home network only**. Do not
port-forward it to the internet — see [SECURITY.md](SECURITY.md).

---

## 2. Preflight checks

### 2.1 Confirm your userland is 64-bit

This is the single most common install failure, and its error message does not point
at the cause. Run **both** commands:

```bash
uname -m                    # kernel architecture
dpkg --print-architecture   # userland architecture
```

You want them to agree:

| `uname -m` | `dpkg --print-architecture` | Verdict |
|---|---|---|
| `aarch64` | `arm64` | Good — a real 64-bit install |
| `x86_64` | `amd64` | Good |
| `aarch64` | **`armhf`** | **Mixed** — see below |
| `armv7l` | `armhf` | 32-bit only — not supported |

A **mixed** Pi runs a 64-bit kernel under a 32-bit userland. This is the default state
of a Raspberry Pi OS install that was upgraded in place from a 32-bit release, and it
is easy to have without knowing. Docker asks the registry for a 32-bit ARM image,
FlightSite publishes only `linux/amd64` and `linux/arm64`, and the pull fails with:

```
no matching manifest for linux/arm/v8 in the manifest list entries
```

**The fix, in order of preference:**

1. **Reinstall with a 64-bit OS.** This is the only configuration FlightSite is tested
   and performance-qualified on ([PERFORMANCE.md §5](PERFORMANCE.md)), and it is what
   a Pi 4 should be running anyway.
2. **Force the platform**, if reinstalling is not practical right now. The images
   themselves run fine — it is only image *selection* that is wrong. Set this in the
   shell, or in an `.env` file next to `compose.yaml`:

   ```bash
   export DOCKER_DEFAULT_PLATFORM=linux/arm64
   ```

   It must be set for every `docker compose` invocation, which is what makes the
   `.env` file the more reliable of the two. Alternatively, pin it per service in
   `compose.yaml`:

   ```yaml
   services:
     flightsite-backend:
       platform: linux/arm64
     flightsite-frontend:
       platform: linux/arm64
   ```

   A 32-bit userland with a 64-bit kernel can execute 64-bit containers, so this
   works. It is a workaround, not a supported configuration.

### 2.2 Check your libseccomp version

```bash
dpkg -l libseccomp2 | tail -1
```

Bullseye-era hosts ship a libseccomp that predates the system calls modern Python
builds use. Rather than letting an unrecognised call through, it kills the process
with `SIGSYS`. Anything from bookworm onward is new enough; on bullseye, the version
in `bullseye-backports` is. The symptom is distinctive and misleading — see
[§9.2](#92-backend-restarts-forever-exit-code-159-and-no-logs).

If your host is bookworm or newer (or any current Ubuntu), you can skip this.

### 2.3 Note your decoder's address and port

You will need this during setup. Two things to get right:

- **Use a LAN IP address, not a `.local` hostname.** `192.168.1.50`, not
  `piaware.local`. See [§9.5](#95-decoder-connection-test-fails-on-a-local-hostname).
- **Note which port the decoder's web UI is on.** It is very often 8080, which is why
  FlightSite publishes itself on 8090 by default.

---

## 3. Install Docker

Use Docker's official convenience script — distribution packages are frequently far
behind and some ship Compose v1, which this project does not support:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Then add yourself to the `docker` group so you do not need `sudo` for every command:

```bash
sudo usermod -aG docker "$USER"
```

**You must now log out and back in.** Group membership is established when your login
session starts, so the change does not apply to the shell you typed it in — including
an existing SSH session. Until you reconnect, every Docker command fails with:

```
permission denied while trying to connect to the Docker daemon socket
```

Reconnect and confirm both pieces work:

```bash
docker run --rm hello-world
docker compose version        # must report v2.x or newer
```

---

## 4. Create the data directory

Everything FlightSite persists — `config.yaml`, `secrets.yaml`, the SQLite database,
logs, and backups — lives under one directory, bind-mounted into the backend
container. Moving that directory plus your `compose.yaml` moves the whole
installation.

```bash
sudo mkdir -p /opt/flightsite/data
sudo chown 1000:1000 /opt/flightsite/data
```

The `chown` is required, not cosmetic. The backend container runs as **uid 1000**
(a non-root user, per [SECURITY.md §7](SECURITY.md)), and a bind mount keeps its host
ownership. A directory owned by root gives a container that cannot create its own
database — see [§9.6](#96-permission-denied-on-the-data-directory).

On most single-user Linux installs your own account is already uid 1000, so
`ls -ld /opt/flightsite/data` showing your username afterwards is expected and correct.
If your account is a different uid, `1000:1000` is still the right answer — it is the
container's uid that matters, not yours.

---

## 5. Get FlightSite and start it

FlightSite ships as prebuilt images; you only need the compose file.

```bash
cd /opt/flightsite          # created in step 4
sudo curl -fsSLO https://raw.githubusercontent.com/stevenpickles/flightsite/main/compose.yaml
```

Or clone the repository if you would rather have the docs and example config locally:

```bash
git clone https://github.com/stevenpickles/flightsite.git
cd flightsite
```

Then pull and start:

```bash
docker compose pull
docker compose up -d
```

Watch it come up:

```bash
docker compose ps            # both services should reach "healthy"
docker compose logs -f       # Ctrl-C to stop following
```

Open **`http://<host-ip>:8090/`** in a browser.

### About port 8090

FlightSite publishes on host port **8090**, not 8080. Decoder web UIs
(dump1090-fa, tar1090, readsb) conventionally own 8080, and FlightSite is usually
installed on the same machine as the decoder — defaulting to 8080 would collide with
the one service you are guaranteed to be running.

To use a different port, set `FLIGHTSITE_HOST_PORT`. There is no need to edit
`compose.yaml`:

```bash
FLIGHTSITE_HOST_PORT=9000 docker compose up -d
```

Or persist it in an `.env` file beside `compose.yaml`:

```
FLIGHTSITE_HOST_PORT=9000
```

Only the published host port changes. The frontend container always listens on 8080
internally, so the right-hand side of the mapping must stay `8080`.

### Trying it without a decoder

To see FlightSite working before you point it at real hardware, start it in demo
mode — a deterministic simulated receiver with about 110 aircraft, including
military, government, police, MLAT, non-positioned and emergency-squawk traffic:

```bash
FLIGHTSITE_DEMO=1 docker compose up -d
```

Demo mode needs no configuration and no decoder, and unlike a real install it starts
producing traffic immediately. Use a separate data directory if you do not want demo
data in your real database (see `FLIGHTSITE_HOST_DATA_DIR` in
[CONFIGURATION.md](CONFIGURATION.md)).

---

## 6. First-run setup

On first load FlightSite redirects you to the setup wizard at `/setup`. It collects
your site name and location, your decoder endpoint (with a live connection test),
units and timezone, aircraft metadata, alert templates and notification preference.

**Finishing the wizard is the whole of setup — no restart needed.** Saving starts the
decoder connection in the running backend and anchors distance and bearing at the
location you entered, so aircraft begin appearing on the Live Map within seconds. The
alert templates you chose are created on the same save.

If the map stays empty, the decoder endpoint is the thing to check rather than the
restart: the Health page (§7 below) reports the decoder connection state directly, and
the wizard's connection test is available again from **Settings → Decoder**.

Settings changed *later* are a different matter for two sections: the decoder endpoint
and the receiver location are read when ingestion starts, so changing either one after
setup does need a backend restart, and the Settings UI marks those sections **"Applies
on next restart"**. See
[CONFIGURATION.md](CONFIGURATION.md#which-settings-need-a-restart) for the full list
of which settings apply live and which wait for a restart.

---

## 7. Verify the install

Give it a minute after finishing the wizard, then check, in order:

1. **The Live Map** at `http://<host-ip>:8090/` shows aircraft.
2. **The Health page** at `http://<host-ip>:8090/health` — reachable from the
   Receiver and Settings pages via the stethoscope icon. This is the place to
   diagnose an install; it shows decoder connection state, time since the last
   aircraft update, ingestion counts, database size and integrity, free disk space,
   backend uptime and version, metadata dataset ages, WebSocket clients, and a list
   of recent errors. **You should not need to SSH into the box to find out whether
   FlightSite is healthy.**
3. From a shell, if you prefer:

   ```bash
   curl -fsS http://localhost:8090/api/v1/health
   ```

   ```json
   {"status":"ok","version":"0.1.0","uptime_s":42.1,
    "counters":{"ingestion_failures":0,"db_errors":0,"enrichment_failures":0,
                "ws_disconnects":0,"live_events_dropped":0},"demo":false}
   ```

A healthy install shows `"status":"ok"` with `ingestion_failures` staying flat over
time. A climbing `ingestion_failures` means FlightSite cannot reach the decoder — go
to the Health page's Decoder card for the specific error.

---

## 8. Upgrading

```bash
cd /opt/flightsite
docker compose pull
docker compose up -d
```

Database migrations run automatically at startup. Take a backup first if you are
upgrading across more than a patch release —
see [BACKUP.md](BACKUP.md#before-upgrading).

---

## 9. Troubleshooting

### 9.1 `no matching manifest for linux/arm/v8`

Your userland is 32-bit. See [§2.1](#21-confirm-your-userland-is-64-bit).

### 9.2 Backend restarts forever, exit code 159, and no logs

The signature is unmistakable once you know it:

```bash
docker compose ps        # flightsite-backend: Restarting (159)
docker compose logs flightsite-backend    # empty, or a truncated startup line
```

Exit 159 is `128 + 31` — **SIGSYS**, "bad system call". The container is killed by the
kernel's seccomp filter before Python can write anything, which is why the logs are
empty. Your host's libseccomp is too old to recognise system calls the runtime uses,
so it denies them instead of allowing them through.

Confirm:

```bash
dpkg -l libseccomp2 | tail -1
```

**Preferred fix — upgrade libseccomp2** (on bullseye, from backports):

```bash
echo 'deb http://deb.debian.org/debian bullseye-backports main' \
  | sudo tee /etc/apt/sources.list.d/backports.list
sudo apt update
sudo apt install -t bullseye-backports libseccomp2
docker compose up -d
```

**Fallback — disable seccomp for the backend.** Add to `compose.yaml`:

```yaml
services:
  flightsite-backend:
    security_opt:
      - seccomp=unconfined
```

Understand the tradeoff: this removes the seccomp sandbox from that container
entirely, so a compromised backend process faces one fewer barrier to the host
kernel. On a trusted LAN appliance that is a defensible risk, but it is strictly
worse than upgrading the library, and it is a permanent change to a file you own.
Prefer the upgrade; use this only when you cannot.

The real fix is a supported 64-bit OS — bookworm and later ship a new enough
libseccomp and this never arises.

### 9.3 `port is already allocated` / `address already in use`

Something else owns the port. Find it:

```bash
sudo ss -lptn 'sport = :8090'
```

Then publish FlightSite somewhere else:

```bash
FLIGHTSITE_HOST_PORT=9000 docker compose up -d
```

If you are upgrading from a build that defaulted to 8080, this is most likely your
decoder's own web UI — that collision is exactly why the default moved to 8090.

### 9.4 `permission denied while trying to connect to the Docker daemon socket`

You are not in the `docker` group *in this session*. Log out and back in; see
[§3](#3-install-docker). `newgrp docker` works as a stopgap for the current shell.

### 9.5 Decoder connection test fails on a `.local` hostname

`.local` names are resolved by mDNS, and the backend container's resolver does not do
mDNS — the base image has no Avahi client. A name that resolves perfectly from your
laptop and from the Pi's own shell will fail from inside the container. The
connection test reports:

```
unreachable — could not reach http://piaware.local:8080/data/aircraft.json:
[Errno -2] Name or service not known
```

"Name or service not known" is the giveaway: this is a name-resolution failure, not a
network or firewall problem.

**Use a LAN IP address instead:** `192.168.1.50`, not `piaware.local`. Give the
decoder a DHCP reservation so the address is stable.

If the decoder runs in another container on the same host, you can instead put both
on a shared Docker network and use its *service name* — Docker's embedded DNS
resolves that inside the network, and it survives IP changes.

Note that `127.0.0.1` in the decoder settings means *inside the backend container*,
not the host. Even for a decoder on the same machine, use the host's LAN IP.

### 9.6 Permission denied on the data directory

Symptoms are a backend that will not start, with a permission error on
`/opt/flightsite/data` or the SQLite file in `docker compose logs flightsite-backend`.

```bash
ls -ld /opt/flightsite/data
sudo chown -R 1000:1000 /opt/flightsite/data
docker compose up -d
```

The container runs as uid 1000 and cannot change ownership of a host bind mount.

### 9.7 The map is blank but aircraft are listed

Basemap tiles come from a third-party provider over the internet; aircraft data does
not. If the map is dark but the aircraft list and counts are populated, FlightSite is
working and tile fetching is not — check the host's internet access, or pick a
different basemap in Settings. Coverage of what leaves your network is in
[SECURITY.md §10](SECURITY.md).

### 9.8 Still stuck

Check the **Health page** first (`/health`) — recent ingestion, database, enrichment
and WebSocket errors are listed there with timestamps. If the backend is unreachable
entirely, that page cannot help, and the logs are next:

```bash
docker compose logs --tail 200 flightsite-backend
```

Logs are also written to `<data-dir>/logs/flightsite.log` and survive a restart.
