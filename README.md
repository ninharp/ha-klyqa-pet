# Klyqa Pet for Home Assistant

Klyqa Pet is a Home Assistant custom integration for Klyqa's pet devices: the
**Welly** water fountain, the **Foody** feeder and the **Airpurifier**. All day-to-day
control — reading sensors, changing settings, dispensing food, switching the fan on —
talks directly to the device's local QConnex REST API over your LAN. The Klyqa cloud
is only used once, during setup, to look up the access token each device needs; after
that the integration never depends on the cloud being reachable.

## Supported devices

| Product ID | Device | Status |
|---|---|---|
| `@klyqa.welly` | Welly water fountain | Supported |
| `@klyqa.welly-dev` | Welly water fountain (development firmware) | Supported |
| `@klyqa.foody` | Foody feeder | Supported |
| `@klyqa.foody-dev` | Foody feeder (development firmware) | Supported |
| `@klyqa.airpurifier2` | Airpurifier (2nd generation) | Supported |
| `@klyqa.airpurifier2-dev` | Airpurifier (2nd generation, development firmware) | Supported |
| `@pfriendly.water-fountain` / `-dev` | Welly, rebranded product ID | Recognised, untested |
| `@pfriendly.foody` / `-dev` | Foody, rebranded product ID | Recognised, untested |
| `@pfriendly.airpurifier` / `-dev` | Airpurifier, rebranded product ID | Recognised, untested |

The `@pfriendly.*` product IDs map to the same device classes as their `@klyqa.*`
counterparts but have not been verified against real hardware.

## Installation

### HACS (recommended)

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Add `https://github.com/ninharp/ha-klyqa-pet` with category **Integration**.
3. Search for "Klyqa Pet" in HACS and install it.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/klyqa_pet` folder from this repository into your Home
   Assistant `config/custom_components` directory.
2. Restart Home Assistant.

### A note on the `pyklyqa-pet` dependency

The integration's `manifest.json` requires the `pyklyqa-pet` library from PyPI so
that HACS and manual installs can pull it in automatically. Until that library is
published, a normal HACS or manual install will fail during setup with "Requirements
for klyqa_pet not found". Until then, run Home Assistant for development with
`--skip-pip-packages pyklyqa-pet` and the repository root on `PYTHONPATH`, so the
in-repo copy of the library is used instead — see
[`docker/README.md`](docker/README.md) for a working example.

## Configuration

Configuration is done entirely from the UI — there is nothing to add to
`configuration.yaml`.

1. Go to **Settings → Devices & services → Add integration** and search for
   **Klyqa Pet**.
2. Choose one of the two setup paths:
   - **Sign in with a Klyqa account** — enter:
     - **Environment** — Production or Test. Use Production unless you have a Klyqa
       test account.
     - **Email** — your Klyqa account email.
     - **Password** — your Klyqa account password.

     The integration signs in once, fetches the access token of every device on the
     account, and sets up a coordinator per device. If a Klyqa device also announces
     itself on the network via mDNS, Home Assistant offers the same choice as a
     discovered flow.
   - **Add a local device (no account)** — for a device that has no cloud account at
     all, for example a re-flashed development board. See below.

### Adding a device manually

Some devices — for example a development unit — are not paired with a cloud account
and are never returned by the cloud login. There are two ways to add one by IP address
and access token instead:

- **A brand new, account-free setup**: on the integration's **Add integration** dialog,
  choose **Add a local device (no account)**. This creates its own "Klyqa Pet (local)"
  entry that never talks to the Klyqa cloud. Adding a second local device the same way
  adds it to that same local entry instead of creating a duplicate.
- **Adding one more manual device to an existing account entry**: open that entry's
  **Configure** dialog and choose **Add a device manually**.

Both forms ask for the same fields:

| Field | Description |
|---|---|
| Host | IP address or hostname of the device |
| Port | REST API port, defaults to `3333` |
| Device access token | The device's access token |

Klyqa development firmware accepts the fixed token `aabbccddeeff0011223344` for local
testing; it is rejected by production firmware.

A device added manually — either way — is never polled with a cloud-issued token, even
if the same id later shows up in a Klyqa account: manually added devices always take
precedence over an account's records for the same device, and a device claimed by a
local (no-account) entry is ignored by every account entry.

## Supported functionality

Every device also exposes these common diagnostic entities (disabled by default,
except where noted):

| Platform | Entity | Notes |
|---|---|---|
| sensor | Wi-Fi signal, Firmware version, SDK version, Last boot | Diagnostic, disabled by default |
| button | Restart | Diagnostic, disabled by default; generic SDK reboot command |

### Welly (water fountain)

| Platform | Entity | Notes |
|---|---|---|
| select | Mode | Sensing, 24h fresh water, water change, self-wash, drain |
| switch | Heating | |
| switch | Light, Ambient light, Sensor mode light, Clean tank low alert, Dirty tank full alert, Super power saving, Telemetry | Config category |
| number | Heating temperature, Daily drinking goal, Radar sensitivity, Circulation pump speed, Clean tank low threshold, Dirty tank full threshold | Config category |
| sensor | Water temperature, Clean tank volume, Sewage tank volume, Drinking volume, Total consumption, Last drinking, Filter life | |
| sensor | Pump status, Power status, Power supply, Descaling status, Light effect, Battery | Power status/supply, descaling status, light effect and battery are diagnostic |
| binary_sensor | Water tray low, Pump problem, Do not disturb, Charging | |
| button | Start descaling, Stop descaling | |

### Foody (feeder)

| Platform | Entity | Notes |
|---|---|---|
| number | Portions | Local helper (1–40) that sets how much the Dispense food button dispenses |
| button | Dispense food, Play voice recording, Query bowl weight | |
| switch | Indicator LED, Pet lock, Beep, Feeding audio, Telemetry | Config category |
| number | Feed audio volume | Config category |
| select | Custom button function, Battery mode, Charging protection | Config category |
| sensor | Bowl remaining, Real-time weight, Feeding state, Bowl state, Food bin, Error state, Last manual feeding, Last manual portions, Last scheduled feeding, Last scheduled portions, Next scheduled feeding | |
| sensor | Battery, MCU firmware version | Diagnostic category |
| binary_sensor | Power, Power adapter, Problem, Food low, Bowl removed | |

The Foody's built-in battery sensor reports "unknown" on units that run only on
mains power, since the device never reports a battery level in that configuration.

### Airpurifier

| Platform | Entity | Notes |
|---|---|---|
| fan | Air purifier | On/off, speed (3 levels), preset modes standalone/auto/night/pet |
| light | LED | On/off, RGB colour and brightness of the ring |
| switch | Ionizer, Child lock, Key tone | Ionizer is a primary control; Child lock and Key tone are config category |
| sensor | PM2.5, Air quality, Filter remaining, Filter life (%), Total run time, Air volume, Pet mode time | |
| binary_sensor | Tilted, Filter removed, Ionizer active | |

## Data updates

Each device is polled independently through its own `DataUpdateCoordinator`:

- Device state is refreshed every **15 seconds**.
- Settings (Welly/Foody) are refreshed every **4th poll (60 seconds)**, since they
  change far less often than state; a settings change made through Home Assistant is
  reflected immediately, without waiting for the next scheduled settings poll.
- System information (firmware/SDK version, last boot, etc.) is refreshed every
  **5 minutes**, since it changes far less often.
- Devices are also discovered passively via mDNS (`_qcxrest._tcp`). If a known
  device's IP address changes, the mDNS listener picks up the new address
  automatically — no reconfiguration needed.

## Example automations

Notify when the Welly's water tray runs low:

```yaml
automation:
  - alias: "Notify when the water tray is low"
    triggers:
      - trigger: state
        entity_id: binary_sensor.klyqa_welly_a1b2c3_water_tray_low
        to: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: "The Welly water tray is running low."
```

Dispense 2 portions from the Foody every morning at 07:00:

```yaml
automation:
  - alias: "Morning feeding"
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.klyqa_foody_d4e5f6_portions
        data:
          value: 2
      - action: button.press
        target:
          entity_id: button.klyqa_foody_d4e5f6_dispense_food
```

Replace the entity IDs above with the ones Home Assistant assigned to your own
devices (Settings → Devices & services → Klyqa Pet → your device).

## Dashboard cards

Ready-to-paste Lovelace card templates, one per device type, using only built-in
cards (no custom cards required):

- [`dashboards/welly.yaml`](dashboards/welly.yaml) — mode, heating, daily drinking goal,
  water/tank sensors and descaling buttons.
- [`dashboards/foody.yaml`](dashboards/foody.yaml) — portions and dispense button, bowl
  and feeding sensors.
- [`dashboards/airpurifier.yaml`](dashboards/airpurifier.yaml) — fan speed/preset
  modes, LED, PM2.5/air quality, ionizer and child lock.

Each file's header comment explains that the entity ids depend on your device's name
and Home Assistant's language, and need adjusting to match your own device. To use one:
open the dashboard you want to add it to, choose **Edit dashboard → Add card**, scroll
to the bottom of the card picker and choose **Manual**, then paste the file's contents
and adjust the entity ids (or use the visual card editor's entity picker instead).

## Known limitations

- Feeding schedules/timers, pet tags, scale calibration, firmware updates and
  uploading custom voice recordings are not exposed by this integration. The
  device's local REST API does not expose all of these, and some (like firmware
  updates) are intentionally left to the manufacturer's app.
- The first-generation Klyqa air purifier (`@klyqa.cleaning.airpurifier1`) uses a
  different local API and is not supported.
- On Foody units that run on mains power only, the battery sensor stays "unknown"
  because the device never reports a battery level.
- Automatic discovery relies on mDNS (`_qcxrest._tcp`), which requires Home
  Assistant to have access to LAN multicast traffic. This works when Home Assistant
  runs natively (Home Assistant OS, Supervised, or a plain Python/venv install) or in
  a container with host networking. It does **not** work in Docker Desktop on macOS,
  because Docker Desktop's networking does not forward multicast traffic to
  containers even with `network_mode: host`. On such setups, use the **Add a device
  manually** option described above instead.

## Troubleshooting

**A device shows as unavailable.** Confirm the device is powered on and on the same
network as Home Assistant, and that Home Assistant can reach it on port `3333`
(`curl -H "Authorization: <token>" http://<device-ip>:3333/api/v1/system/info`). If
the device was previously discovered via mDNS and has since changed its IP address,
wait for the next mDNS announcement or restart Home Assistant to force a re-resolve.

**A re-flashed development board isn't listed by the cloud account, or the cloud's
token/product id for it is stale.** This is expected for a board whose id is derived
from its MAC address: re-flashing does not change the MAC, so the cloud entry (if any)
still describes the board's previous firmware. Add it with **Add a local device (no
account)** or **Add a device manually** instead of relying on the account — see
[Adding a device manually](#adding-a-device-manually). Once added this way, the device
keeps its own token and is never touched by an account's cloud token refresh, even if
the same id is also listed by an account.

**A device rejects its access token.** This affects only that one device: it becomes
unavailable and the log shows a warning naming it ("… rejects the access token from
the Klyqa account; re-pair the device in the Klyqa app"). This does **not** trigger a
re-authentication prompt — the integration first tries to recover by fetching a fresh
token from the cloud, and only asks you to sign in again if that cloud login itself
fails (see below). To fix a device stuck like this, either re-pair it in the Klyqa app
so the cloud hands out a new token, or remove and re-add it with **Add a device
manually** using its current token.

**The integration asks you to re-authenticate.** This happens only when the Klyqa
cloud itself rejects your account password (not when an individual device rejects its
token). Go to the integration's entry and follow the re-authentication prompt with
your current password.

**A device intermittently shows as unavailable even though it is reachable.** The
device firmware allows at most 3 REST requests per 300 ms and answers further requests
with an error until that window passes. The integration already spaces out and retries
its own requests to stay under this limit, so a device flipping to "unavailable" like
this usually means something else is polling it at the same time — the Klyqa app, or
the same device added to Home Assistant a second time. The log then names the affected
device: "… is rate limiting requests; another client (for example the Klyqa app) is
polling it at the same time". Close the other client, or wait for the poll to succeed.

**Enable debug logging** to see the raw REST requests/responses:

```yaml
logger:
  default: info
  logs:
    custom_components.klyqa_pet: debug
    pyklyqa_pet: debug
```

If you need to file an issue, first download the integration's diagnostics
(Settings → Devices & services → Klyqa Pet → your device → Download diagnostics) —
this redacts your email, password and access tokens and includes the raw device
state, which is invaluable for debugging.

## Removal

Removing the integration is a single step: go to **Settings → Devices & services**,
open the Klyqa Pet entry, and choose **Delete**. All devices and entities created by
the integration are removed from Home Assistant. Nothing is changed on the physical
devices themselves — no factory reset, no token revocation — so they keep working
with the Klyqa app.

## Development

This repository contains both the `pyklyqa_pet` client library and the
`custom_components/klyqa_pet` integration, developed together.

```bash
uv venv
uv pip install -e ".[dev]"
pytest
```

- A Dockerised Home Assistant instance for manual testing is described in
  [`docker/README.md`](docker/README.md).
- `scripts/probe_devices.py` discovers Klyqa devices on the LAN via mDNS and dumps
  their system info and state — useful for verifying connectivity and firmware
  behaviour outside of Home Assistant.
- `brands/klyqa_pet/` contains the icon and logo assets prepared for submission
  to [home-assistant/brands](https://github.com/home-assistant/brands). The same
  files are also copied into `custom_components/klyqa_pet/brand/` as an interim
  fallback so HACS's brand check passes before that submission is merged; once
  the `home-assistant/brands` PR lands, the icon shown in Home Assistant's UI
  comes from there and the local copy can be removed.
- The integration implements the Home Assistant Bronze through Platinum quality
  scale rules (see `custom_components/klyqa_pet/quality_scale.yaml`), except for the
  `brands` rule: the assets above still need to be submitted and merged upstream
  before that rule — and the manifest's `quality_scale` claim — can be marked done.

Pull requests are welcome at
[github.com/ninharp/ha-klyqa-pet](https://github.com/ninharp/ha-klyqa-pet).
