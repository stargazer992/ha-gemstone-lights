<img src="custom_components/gemstone_lights/brand/icon.png" width="96" align="right" alt="">

# Gemstone Lights for Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5)](https://my.home-assistant.io/redirect/hacs_repository/?owner=xagon0&repository=ha-gemstone-lights&category=integration)
[![Latest release](https://img.shields.io/github/v/release/xagon0/ha-gemstone-lights)](https://github.com/xagon0/ha-gemstone-lights/releases/latest)
[![Validate](https://github.com/xagon0/ha-gemstone-lights/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/xagon0/ha-gemstone-lights/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/xagon0/ha-gemstone-lights)](LICENSE)

**Local control** for [Gemstone Lights](https://www.gemstonelights.com/)
**Hub2** in Home Assistant.

Control your permanent outdoor lighting directly over your LAN or optional
Bluetooth, with optional Gemstone account import and cloud fallback.
**Local-only mode needs no account and makes no Gemstone cloud
requests.** See [Local operation](LOCAL_OPERATION.md) for offline setup, content
editing, playlists, schedules, evidence and the remaining protocol gaps.

## Quick install

[![Open Gemstone Lights in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=xagon0&repository=ha-gemstone-lights&category=integration)

Requires HACS to be installed. Open the link, select **Download**, restart Home
Assistant, then follow [Setup](#setup).

## Features

- **Light entity** - on/off, RGB colour, brightness, and all 29 built-in
  animations exposed as Home Assistant effects (chase, fireworks, glitter,
  marquee, pacman, spectrum, wave, and more).
- **A light per zone** - every zone you created in the Gemstone app becomes its
  own light with its own colour and effect, much like WLED segments. The names
  are yours, whatever you called them, and zones added or renamed later are
  picked up without reconfiguring anything. This is how you drive front and
  back independently.
- **Effect speed** - a slider that also re-applies the running effect.
- **Design select** - play locally saved or imported architectural designs.
- **Pattern select** - play locally created or imported patterns.
- **The whole official library** - Gemstone publishes well over a thousand
  patterns. Browsing them is split across two dropdowns, *Library folder* and
  *Library pattern*, because no single list of that size is usable. Automations
  can reach any of them directly with the `play_library_pattern` service.
- **Now playing sensor** - what the controller is currently showing, plus
  firmware, output names and local IP as attributes.
- Optional account import discovers controllers and zones across homegroups.
- **Local editing and backups** - create patterns, designs and static zones; save
  current content; import and export portable catalogs.
- **Local automation blueprints** - playlists, weekly schedules and sunset/sunrise.
- **Local control** - commands go straight to the controller on your network,
  so they apply immediately and keep working when the internet is down. The
  address can be entered manually or imported from an account. Cloud fallback
  and downloads are disabled completely in local-only mode.

Zone control preserves single-pixel and noncontiguous selections, including
unselected gaps. Existing native animated zones must retain their complete
controller-defined selection.

Effects and colours are built on the fly, so you are not limited to patterns
you saved in the app first.

## Installation

Requires **Home Assistant 2026.9.1 or later**. Development and CI use that exact
version with Python 3.14.2 or newer within 3.14.

### HACS (recommended)

Gemstone Lights is included in the default HACS catalog.

1. Open **HACS** in Home Assistant and search for **Gemstone Lights**.
2. Open **Gemstone Lights** and select **Download**.
3. Restart Home Assistant, then follow [Setup](#setup) below.

#### Custom repository fallback

If Gemstone Lights does not appear in search, add it as a custom repository:

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Enter `https://github.com/xagon0/ha-gemstone-lights`, select type
   **Integration**, and choose **Add**.
3. Follow the search, download, and restart steps above.

### Manual

Copy `custom_components/gemstone_lights` into your Home Assistant
`custom_components` directory and restart.

## Setup

**Settings → Devices & Services → Add Integration → Gemstone Lights** offers:

- **Local controller**: enter a provisioned Hub2's address. Local commands must
  already be enabled. No Gemstone credentials are requested.
- **Bluetooth controller**: enter a provisioned Hub2's Bluetooth address. Requires
  a connectable HA adapter or active proxy in range; no account or controller Wi-Fi
  is needed. Firmware 1.1.5 verified; protected firmware is unsupported.
- **Import from a Gemstone account**: sign in to discover devices, zones and
  catalogs. Credentials are stored in the config entry for optional cloud access.

For an existing entry, choose **Configure → Disable all Gemstone cloud access**
to preserve its entities and cached content while switching to offline operation.
Reserve the controller's DHCP address. The options form can override an address
for the selected controller without changing entity IDs. A Bluetooth address
replaces LAN for that selected controller; clear it to return to LAN. Close the
vendor app's Bluetooth connection before HA connects.

## Local control

"Allow Local Commands" (Device Settings → Advanced Settings in the Gemstone app)
opens an unauthenticated HTTP service on the controller's LAN address. In account
setup or **Configure**, the **Automatically enable Allow Local Commands** option
lets the integration turn this setting on for the account's controllers. It is
unchecked by default. Leaving it unchecked keeps the controller setting unchanged:
controllers already enabled can still use LAN; otherwise, account mode uses cloud
control. Local-only LAN setup requires the setting to be enabled beforehand.

Upgrading to 1.8.1 clears the integration's previous automatic-enable preference
because it was preselected in older versions. Opt in again under **Configure** if
you want this behavior. The upgrade does not change the controller's current
"Allow Local Commands" setting.

The Now playing sensor's
`control` attribute reports `local` (LAN), `bluetooth`, or `cloud`. Bluetooth
state control does not require the HTTP local-command switch.

Known addresses, zones, patterns, designs and library content are persisted.
Local-only mode restores them without logging in or refreshing cloud catalogs.
Failed local reads mark the controller unavailable and retry on the next poll;
commands never fall back to the cloud while it is disabled.

Verified on Hub2 firmware 1.1.5:

| Feature | Local path |
| --- | --- |
| Power, RGBW, brightness, whole-run animations | Direct controller commands |
| Static zone palettes, including new HA zones | Explicit pixel colors |
| Existing animated controller zones | Native `zonePatterns` |
| Pattern/design editing and saved content | HA local catalog |
| Playlists and schedules | Included HA blueprints; HA must remain running |
| Firmware and output settings | Read only |

Native zone/timer management is not yet exposed in HA; newly verified commands
and remaining work are documented in [Native management](MANAGEMENT_PROTOCOL.md).
Firmware updates, music sync and first-time controller provisioning remain unresolved. Full details and evidence are in
[Local operation](LOCAL_OPERATION.md). The earlier claim that Hub2 cannot render
`zonePatterns` locally was disproved by direct LAN and camera tests.

### A quirk worth knowing

The controller silently ignores writes that arrive back to back: it answers
`200` and keeps its previous state. The integration serialises writes and
spaces them, which is why a burst of rapid commands settles a second or two
later rather than being lost.

## The pattern library

In account mode, Gemstone's official library is fetched and refreshed daily:
roughly 1,700 patterns across 68 folders, grouped into categories such as
sports, holidays and everyday. Downloaded or imported content remains usable
offline; local-only mode never refreshes it from the vendor.

Pick a folder in **Library folder**, then a pattern in **Library pattern**;
choosing a folder does not change the lights. From an automation, skip the
browsing:

```yaml
action: gemstone_lights.play_library_pattern
target:
  entity_id: light.your_controller
data:
  pattern: Happy New Year
  folder: holidays / Chinese New Year   # optional
```

An unknown name fails with a list of near matches rather than silently doing
nothing. Turn the library off in the integration's options if you do not want
it loaded.

## Notes and limitations

- **Zone edits preserve neighboring patterns**, including their complete RGBW
  palettes, speed, direction, and vendor settings. Parallel edits are queued per
  controller and use the most recently accepted command.
- **Solid zones have independent brightness over the LAN.** Dimming the whole
  design retains their relative brightness. A zone-targeted library action plays
  the complete library pattern only in that zone.
- **External pixel layouts that cannot be represented by the configured zones**
  produce a clear error on zone edits, so unrelated pixels are not silently lost.
  Select a zone design first. Per-zone edits during playlists or music mode are
  also unsupported.

- **Brightness** is a real, separate value over local control. Over the cloud
  there is no brightness field for a solid colour, so it is folded into the
  colour instead.
  HA remembers the original color for commands it sends, so dimming and restoring
  brightness does not repeatedly scale an already-dimmed color. If an externally
  changed cloud color has no separate brightness field, the original color and
  dimmer setting cannot be reconstructed; HA uses the reported color at 255.
- **Brightness applies to whatever is playing.** Dimming the light while a
  saved pattern, library pattern or design is on re-sends that same content
  with the new brightness, so multi-colour patterns and per-zone designs are
  kept. Changing only the effect likewise keeps the pattern's colours.
- **State lags slightly.** The cloud takes a moment to reflect a change, so the
  integration immediately shows accepted commands, protects them from stale
  echoes for five seconds, re-reads state after commands, and polls every 30
  seconds. Failed reads mark the affected controller unavailable instead of
  reporting a false off state.
- **Changing speed while off leaves the lights off.** It stores the speed for
  future effects; running patterns are updated immediately.
- **Music mode and native controller playlist management** remain unimplemented.
  HA-based playlists are provided as a script blueprint.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pinned test environment, behavior-test
standards, and controller smoke-test procedure. The repository review is recorded
in [REVIEW.md](REVIEW.md), and release changes in [CHANGELOG.md](CHANGELOG.md).

## The local API

Served unauthenticated on port 80 once "Allow Local Commands" is enabled. This
is the interface the vendor's own Control4 and Elan drivers use, and it is
verified working against a Hub2 on firmware 1.1.5.

```http
GET  /device-state/currently-playing   -> state.reported.currentlyPlaying
GET  /device-state/hub-settings        -> state.reported.hubSettings
POST /device-control/play
```

```json
{"state": {"desired": {"currentlyPlaying": {
  "onState": true,
  "colorB": {"value": 255, "brightness": 180},
  "pattern": null, "architectural": null, "impulse": null, "playlist": null
}, "origin": "control4"}}}
```

`currentlyPlaying` carries `onState` plus exactly one of `colorB`, `pattern` or
`architectural`; send the others as null. Power changes send `onState` alone so
the controller keeps showing what it had. Payloads are limited to 15 KiB.
`hub-settings` reports firmware, per-output pixel counts and the RGBW ordering.

## Colour format

Colours are packed as **`R | G << 8 | B << 16 | W << 24`** — little-endian
RGBW, so the hex reads `WWBBGGRR`. Red is `255`, green `65280`, blue
`16711680`, and the dedicated white channel `4278190080`. Note that the last of
those cannot be expressed as 24-bit RGB, which is the giveaway that these are
RGBW fixtures with a real white channel rather than plain RGB.

## The cloud API, for anyone building on this

Everything below was determined by observing the official Android app. It is
recorded here so nobody has to repeat the work.

Auth is **AWS Cognito** (user pool `us-west-2_rr5lY7Etr`, client
`2647t144niotrl53vvru0ivno7`, SRP). Requests then carry a plain bearer token —
**there is no AWS request signing**, despite the error messages suggesting
otherwise.

Base URL: `https://mytpybpq12.execute-api.us-west-2.amazonaws.com/prod`

Required headers:

```
authorization: Bearer <cognito access token>
app-environment: Production
content-type: application/json
```

Two traps cost the most time:

1. **All writes are `PUT`.** Sending `POST` returns
   `Invalid key=value pair (missing equal-sign) in Authorization header`, which
   looks like a SigV4 signing failure and is thoroughly misleading.
2. **The query parameter name differs by endpoint.** Most take
   `deviceOrGroupId`; the architectural (per-zone) endpoints take `deviceId`.

| Method | Path | Params | Body |
| --- | --- | --- | --- |
| GET | `/homegroup/list` | | |
| GET | `/homegroup/devices` | `homegroupId` | |
| GET | `/deviceControl/currentlyPlaying` | `deviceOrGroupId` | |
| GET | `/deviceControl/zone/list` | `deviceId` | |
| GET | `/deviceControl/architectural/list` | `deviceId` | |
| GET | `/folders/list` | | |
| GET | `/folders/pattern/list` | `folderId` | |
| PUT | `/deviceControl/onState` | `deviceOrGroupId` | `{"onState": true}` |
| PUT | `/deviceControl/play/color` | `deviceOrGroupId` | `{"color": 65280}` |
| PUT | `/deviceControl/play/pattern` | `deviceOrGroupId` | `{"pattern": {...}}` |
| PUT | `/deviceControl/play/architectural` | `deviceId` | `{"architectural": {...}}` |
| PUT | `/deviceControl/deviceSettings` | `deviceId` | `{"tcpEnabled": true}` |

`deviceSettings` also reports `localIp`, `pixelCount` and `tcpEnabled`. Setting
`tcpEnabled` genuinely opens and closes the controller's local HTTP port, so
local control can be switched on without touching the app.

Patterns do not have to exist in the account: the controller will play any
well-formed pattern object, which is what makes free-form effect selection
possible. A pattern looks like:

```json
{"name": "…", "colors": [16711680], "animation": "chase", "speed": 200,
 "brightness": 255, "direction": 0, "backgroundColor": 0, "id": "<uuid>"}
```

Valid `animation` values are the 29 names shipped with the app: accent, around,
chase, eyeball, fade, fireworks, flicker, flow, ghost, glitch, glitter,
gradient, gradient_wave, isofade, marquee, motionless, multipulse, pacman,
pulse, pyramid_chase, smooth, spectrum, spotlight, stack, starry, stretch,
sway, tremor, wave.

Per-zone output uses an architectural design whose `zonePatterns` list maps a
`zoneId` (from `/deviceControl/zone/list`) to a pattern. The call replaces the
whole design, so send every zone you want lit on each request.

`currentlyPlaying` returns `onState`, `color`,
`pattern`, `architectural` and `playlist`, where only one of the last three is
set at a time. Pattern bodies are the `patternData` object from
`/folders/pattern/list`; design bodies are an object from
`/deviceControl/architectural/list` with `preview: false` added.

## Credits

The local protocol was recovered independently from the vendor's Control4 and
Elan drivers, which agree on it. Thanks to that work for making local control
possible.

## Disclaimer

Not affiliated with, endorsed by, or supported by Gemstone Lights. It relies on
a private API that the vendor may change at any time. Use at your own risk.

## License

MIT

## Local-service recovery

Cloud-capable entries can fall back to cloud control when the controller's LAN
service fails. A manual soft-reboot action and opt-in automatic recovery can
restore the controller's local service. The Now playing sensor's
`recovery_status` attribute explains whether recovery is waiting, in cooldown,
or exhausted for the current outage.

If automatic recovery is exhausted, an administrator can re-arm it in
**Developer tools → Actions**:

```yaml
action: gemstone_lights.rearm_recovery
data:
  controller: light.your_controller
```

Automatic recovery must already be enabled. Re-arming resets the failure
observation window and preserves the cooldown from the last reboot attempt.
Another attempt requires fresh LAN failures spanning the configured duration
and expiry of the remaining cooldown. The action itself does not reboot the
controller or change its settings. See [recovery configuration and limits](RECOVERY.md).
