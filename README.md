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

## Configuration

Configuration is done entirely from the UI — there is nothing to add to
`configuration.yaml`.

1. Go to **Settings → Devices & services → Add integration** and search for
   **Klyqa Pet**.
2. Enter:
   - **Environment** — Production or Test. Use Production unless you have a Klyqa
     test account.
   - **Email** — your Klyqa account email.
   - **Password** — your Klyqa account password.
3. The integration signs in once, fetches the access token of every device on the
   account, and sets up a coordinator per device. If a Klyqa device also announces
   itself on the network via mDNS, Home Assistant offers the same sign-in dialog as a
   discovered flow — accept it and sign in with the account the device is paired with.

### Adding a device manually

Some devices — for example a development unit — are not paired with a cloud account
and are never returned by the cloud login. For these, open the integration's
**Configure** dialog and choose **Add a device manually**:

| Field | Description |
|---|---|
| Host | IP address or hostname of the device |
| Port | REST API port, defaults to `3333` |
| Device access token | The device's access token |

Klyqa development firmware accepts the fixed token `aabbccddeeff0011223344` for local
testing; it is rejected by production firmware.

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
| light | LED | On/off and RGB colour of the ring; brightness is read-only (see Known limitations) |
| switch | Ionizer, Child lock, Key tone | Ionizer is a primary control; Child lock and Key tone are config category |
| sensor | PM2.5, Air quality, Filter remaining, Filter life (%), Total run time, Air volume, Pet mode time | |
| binary_sensor | Tilted, Filter removed, Ionizer active | |

## Data updates

Each device is polled independently through its own `DataUpdateCoordinator`:

- Device state and settings are refreshed every **15 seconds**.
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

## Known limitations

- Feeding schedules/timers, pet tags, scale calibration, firmware updates and
  uploading custom voice recordings are not exposed by this integration. The
  device's local REST API does not expose all of these, and some (like firmware
  updates) are intentionally left to the manufacturer's app.
- The Airpurifier's LED brightness is read-only; the firmware provides no way to set
  it, only to read the current value and toggle between automatic and custom colour.
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
(`curl http://<device-ip>:3333/device/state`). If the device was previously
discovered via mDNS and has since changed its IP address, wait for the next mDNS
announcement or restart Home Assistant to force a re-resolve.

**The integration reports that a device "rejected the access token".** This means
the device (or account) requires you to sign in again. Go to the integration's entry
and follow the re-authentication prompt with your current password. If the device
itself was re-paired with the Klyqa app (which rotates its token), remove and
re-add it, or use **Add a device manually** with the new token.

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
  to [home-assistant/brands](https://github.com/home-assistant/brands).
- The integration implements the Home Assistant Bronze through Platinum quality
  scale rules (see `custom_components/klyqa_pet/quality_scale.yaml`), except for the
  `brands` rule: the assets above still need to be submitted and merged upstream
  before that rule — and the manifest's `quality_scale` claim — can be marked done.

Pull requests are welcome at
[github.com/ninharp/ha-klyqa-pet](https://github.com/ninharp/ha-klyqa-pet).
