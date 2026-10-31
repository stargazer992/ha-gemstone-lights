<img src="custom_components/gemstone_lights/brand/icon.png" width="96" align="right" alt="">

# Gemstone Lights for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stargazer992&repository=ha-gemstone-lights&category=integration)
[![Latest release](https://img.shields.io/github/v/release/stargazer992/ha-gemstone-lights)](https://github.com/stargazer992/ha-gemstone-lights/releases/latest)
[![Validate](https://github.com/stargazer992/ha-gemstone-lights/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/stargazer992/ha-gemstone-lights/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/stargazer992/ha-gemstone-lights)](LICENSE)

**Local control** for [Gemstone Lights](https://www.gemstonelights.com/)
**Hub2** in Home Assistant.

Control your permanent outdoor lighting directly over your LAN or optional
Bluetooth. **The integration never uses the Gemstone cloud at runtime.** An
optional one-time account import copies a controller's setup, zones, designs and
saved patterns, and downloads the official pattern library to `www/gemstones`. See [Local operation](LOCAL_OPERATION.md) for offline setup, content
editing, playlists, schedules and supported features.

## Quick install

[![Open Gemstone Lights in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stargazer992&repository=ha-gemstone-lights&category=integration)

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
- **Official pattern library** - downloaded once to `www/gemstones`; browse it
  with the *Library folder* and *Library pattern* dropdowns, or use the
  `play_library_pattern` action in automations.
- **Now playing sensor** - current controller state, firmware, output names
  and local IP.
- **Health sensors** - *Response time* of the last status read and *Missed
  polls* since Home Assistant started, to spot an unreliable controller.
- Optional one-time account import of controller setup, zones, designs and
  saved patterns. Patterns with the same name in different folders are listed
  as `Name (Folder)`.
- **Local editing and backups** - create patterns, designs and static zones; save
  current content; import and export portable catalogs.
- **Favorites backup** - `backup_favorites` saves a controller's patterns,
  designs and zones to `<config>/gemstone_backups/`; `restore_favorites` merges
  the newest (or a named) file back. Home Assistant backups include that folder.
- **Local automation blueprints** - playlists, weekly schedules and sunset/sunrise.
- **Local control** - commands go directly to the controller on your network
  and work without an internet connection. The address can be entered manually
  or imported from an account.

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
2. Enter `https://github.com/stargazer992/ha-gemstone-lights`, select type
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
- **Import from a Gemstone account**: sign in once to copy one controller's
  setup (light count, output names, colour order, LAN address), native zones,
  designs and saved patterns, and to save the official library to
  `www/gemstones` (created if missing). The password is not stored. Run the
  import again to add another controller. If the imported address does not
  answer, setup asks for it.

**Configure** offers three steps:

- **Controller connection**: LAN address override or Bluetooth address.
- **Re-import from Gemstone account**: sign in once to refresh the controller's
  setup, zones, designs, saved patterns and the library. The password is not kept.
- **Cloud access** (off by default): stores your Gemstone credentials so commands
  and state reads fall back to the cloud when the controller does not answer
  locally, and enables the `soft_reboot` action. Turning it off deletes the
  stored credentials. The Now playing sensor's `control` attribute then shows
  `cloud` while the cloud is in use.

Entries created by earlier versions with an account are converted on upgrade:
credentials are removed and cached controllers, zones, designs and saved
patterns are kept; a cached library is moved to `www/gemstones`.
Reserve the controller's DHCP address. The options form can override an address
for the selected controller without changing entity IDs. A Bluetooth address
replaces LAN for that selected controller; clear it to return to LAN. Close the
vendor app's Bluetooth connection before HA connects.

## Local control

"Allow Local Commands" (Device Settings → Advanced Settings in the Gemstone app)
opens an unauthenticated HTTP service on the controller's LAN address. The
account import's **Switch on Allow Local Commands if it is off** option, unchecked
by default, lets the import turn it on once. Local LAN setup requires the
setting to be enabled beforehand. Bluetooth control does not require it.

The Now playing sensor's `control` attribute reports `local` (LAN) or
`bluetooth`.

Only the controller setup, zones, designs and saved patterns are stored by the
integration. Speed, browsing state and command history are kept in memory.
A controller is marked unavailable after three failed reads in a row; a
command is always sent to the controller, even right after a failed poll.
Controllers are polled in parallel, and a slow read never delays a command.

Verified on Hub2 firmware 1.1.5:

| Feature | Local path |
| --- | --- |
| Power, RGBW, brightness, whole-run animations | Direct controller commands |
| Static zone palettes, including new HA zones | Per-pixel colours |
| Animated zones imported from the controller | Controller zone patterns |
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

The account import saves Gemstone's official library once to
`<config>/www/gemstones/`: an `index.json` plus one JSON file per folder,
roughly 1,700 patterns across 68 folders. Home Assistant reads it from these
files at startup; delete the folder to remove it. Files in `www` are served
without login at `/local/gemstones/`. The library is never refreshed.

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

Unknown pattern names produce an error with suggested matches.

To play a saved design or pattern by name, on one or several controllers at
once, use `play_by_name`. It looks in saved designs, then saved patterns, then
the library:

```yaml
action: gemstone_lights.play_by_name
target:
  entity_id: [light.backside, light.front]
data:
  name: Glamo WW   # or "Glamo WW (Holiday)" when two share a name
```

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
- **Brightness** is controlled separately from colour.
- **Dimming preserves patterns and designs**, including their colours and zones.
  Changing an effect also preserves the pattern's colours.
- **State updates** run every 30 seconds and after commands. Three failed reads
  in a row mark the affected controller unavailable.
- **Patterns or zones changed in the Gemstone app later** are not picked up;
  run the import again for a new controller, or recreate them in HA.
- **Animated zones** need zones imported from the controller with unchanged
  pixels; verified on firmware 1.1.5. New or resized HA zones support
  motionless palettes only.
- **Choosing None in a dropdown changes nothing**; it only shows that nothing
  saved is playing. Turn the lights off with the light entity.
- **Changing speed while off leaves the lights off.** It stores the speed for
  future effects; running patterns are updated immediately.
- **Music mode and native controller playlist management** remain unimplemented.
  HA-based playlists are provided as a script blueprint.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development, testing and protocol
references, and [CHANGELOG.md](CHANGELOG.md) for release changes.

## Disclaimer

This integration is not affiliated with, endorsed by, or supported by Gemstone
Lights. It uses undocumented interfaces that may change with vendor updates.

## License

[MIT](LICENSE)
