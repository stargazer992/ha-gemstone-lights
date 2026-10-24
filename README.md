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
editing, playlists, schedules and supported features.

## Quick install

[![Open Gemstone Lights in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=xagon0&repository=ha-gemstone-lights&category=integration)

Requires HACS to be installed. Open the link, select **Download**, restart Home
Assistant, then follow [Setup](#setup).

## Features

- **Light entity** - on/off, RGB colour, brightness, and all 29 built-in
  animations exposed as Home Assistant effects.
- **Zone lights** - separate colour and effect control for each zone configured
  in the Gemstone app. Zone additions and name changes are detected automatically.
- **Effect speed** - a slider that also re-applies the running effect.
- **Design select** - play locally saved or imported architectural designs.
- **Pattern select** - play locally created or imported patterns.
- **Official pattern library** - browse patterns using the *Library folder* and
  *Library pattern* dropdowns, or use the `play_library_pattern` action in automations.
- **Now playing sensor** - current controller state, firmware, output names
  and local IP.
- Optional account import discovers controllers and zones across homegroups.
- **Local editing and backups** - create patterns, designs and static zones; save
  current content; import and export portable catalogs.
- **Local automation blueprints** - playlists, weekly schedules and sunset/sunrise.
- **Local control** - commands go directly to the controller on your network
  and work without an internet connection. The address can be entered manually
  or imported from an account. Cloud fallback
  and downloads are disabled completely in local-only mode.

Zone control preserves single-pixel and noncontiguous selections, including
unselected gaps. Existing native animated zones must retain their complete
controller-defined selection.

Choose colours and effects directly in Home Assistant without first saving a
pattern in the Gemstone app.

## Installation

Requires **Home Assistant 2026.9.1 or later**.

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

The Now playing sensor's `control` attribute reports `local` (LAN), `bluetooth`,
or `cloud`. Bluetooth control does not require the HTTP local-command switch.

Known addresses, zones, patterns, designs and library content are saved locally.
Local-only mode restores them without logging in or refreshing cloud catalogs.
Failed local reads mark the controller unavailable and retry on the next poll;
commands never fall back to the cloud while it is disabled.

Verified on Hub2 firmware 1.1.5:

| Feature | Local path |
| --- | --- |
| Power, RGBW, brightness, whole-run animations | Direct controller commands |
| Static zone palettes, including new HA zones | Per-pixel colours |
| Existing animated controller zones | Controller zone patterns |
| Pattern/design editing and saved content | HA local catalog |
| Playlists and schedules | Included HA blueprints; HA must remain running |
| Firmware and output settings | Read only |

Native controller zone and timer management, firmware updates, music sync and
first-time controller setup are not supported by this integration. See
[Local operation](LOCAL_OPERATION.md) for details.

### Command timing

The controller may ignore commands sent too close together. The integration
queues and spaces commands, so rapid changes may take a second or two to complete.

## Pattern library

In account mode, Gemstone's official library is fetched and refreshed daily:
roughly 1,700 patterns across 68 folders, grouped into categories such as
sports, holidays and everyday. Downloaded or imported content remains usable
offline; local-only mode never refreshes it from the vendor.

Pick a folder in **Library folder**, then a pattern in **Library pattern**;
choosing a folder does not change the lights. To play a pattern from an automation:

```yaml
action: gemstone_lights.play_library_pattern
target:
  entity_id: light.your_controller
data:
  pattern: Happy New Year
  folder: holidays / Chinese New Year   # optional
```

Unknown pattern names produce an error with suggested matches. The library can
be disabled in the integration's options.

## Notes and limitations

- **Zone edits preserve neighboring patterns**, including their complete RGBW
  palettes, speed, direction, and vendor settings. Parallel edits are queued per
  controller and use the most recently accepted command.
- **Solid zones have independent brightness over the LAN.** Dimming the whole
  design retains their relative brightness. A zone-targeted library action plays
  the complete library pattern only in that zone.
- **External pixel layouts that cannot be represented by the configured zones**
  produce an error on zone edits, leaving the current output unchanged.
  Select a zone design first. Per-zone edits during playlists or music mode are
  also unsupported.
- **Brightness** is controlled separately from colour over LAN. Cloud control
  applies solid-colour brightness to the colour values. Home Assistant remembers
  the original colour for its own commands, but cannot recover the original
  brightness when another app changes a solid colour through the cloud.
- **Dimming preserves patterns and designs**, including their colours and zones.
  Changing an effect also preserves the pattern's colours.
- **State updates** run every 30 seconds and after commands. Cloud updates can
  be delayed. Failed reads mark the affected controller unavailable.
- **Changing speed while off leaves the lights off.** It stores the speed for
  future effects; running patterns are updated immediately.
- **Music mode and native controller playlist management** remain unimplemented.
  HA-based playlists are provided as a script blueprint.

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

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development, testing and protocol
references, and [CHANGELOG.md](CHANGELOG.md) for release changes.

## Disclaimer

This integration is not affiliated with, endorsed by, or supported by Gemstone
Lights. It uses undocumented interfaces that may change with vendor updates.

## License

[MIT](LICENSE)
