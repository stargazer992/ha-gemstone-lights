# Hub2 API reference

Implementation notes for contributors. Local protocol research used Gemstone
Lights' Control4 and Elan drivers; cloud protocol research used the official
Android app. These observations are not a vendor specification.

For setup and supported features, see [Local operation](LOCAL_OPERATION.md).
Bluetooth is documented in [BLUETOOTH_PROTOCOL.md](BLUETOOTH_PROTOCOL.md), and
native management findings in [MANAGEMENT_PROTOCOL.md](MANAGEMENT_PROTOCOL.md).

## Local API

The controller serves an unauthenticated HTTP API on port 80 when "Allow Local
Commands" is enabled. This interface was verified on Hub2 firmware 1.1.5.

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

For colour, pattern or design changes, send the active content field and clear
the other content fields. Power changes send `onState` alone to preserve current
content. Payloads are limited to 15 KiB. `hub-settings` reports firmware,
per-output pixel counts and RGBW ordering.

## Colour format

Colours are packed as `R | G << 8 | B << 16 | W << 24` (little-endian RGBW),
displayed in hexadecimal as `WWBBGGRR`. Red is `255`, green is `65280`, blue is
`16711680`, and white is `4278190080`.

## Cloud API

Cloud access is optional and disabled in local-only mode. The client implementation
is in [api.py](custom_components/gemstone_lights/api.py). The API base URL, Cognito
identifiers and application headers are defined in
[const.py](custom_components/gemstone_lights/const.py).

Authentication uses AWS Cognito SRP. API requests carry the authenticated
account's access token over HTTPS; they do not use AWS SigV4 request signing.

Lighting writes use `PUT`. Sending `POST` to these endpoints can return
`Invalid key=value pair (missing equal-sign) in Authorization header`, even
though AWS request signing is not required. Most endpoints use `deviceOrGroupId`;
zone and architectural endpoints use `deviceId`.

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

`deviceSettings` reports `localIp`, `pixelCount` and `tcpEnabled`. Changing
`tcpEnabled` opens or closes the controller's local HTTP service. The integration
must leave this setting unchanged unless the user explicitly opts in to automatic
enabling.

## Patterns and designs

Patterns can be supplied directly without first saving them in the account:

```json
{"name": "Example", "colors": [16711680], "animation": "chase", "speed": 200,
 "brightness": 255, "direction": 0, "backgroundColor": 0, "id": "<uuid>"}
```

Supported `animation` values: accent, around, chase, eyeball, fade, fireworks,
flicker, flow, ghost, glitch, glitter, gradient, gradient_wave, isofade, marquee,
motionless, multipulse, pacman, pulse, pyramid_chase, smooth, spectrum, spotlight,
stack, starry, stretch, sway, tremor, wave.

Per-zone output uses an architectural design whose `zonePatterns` list maps a
`zoneId` from `/deviceControl/zone/list` to a pattern. The call replaces the whole
design, so include every zone that should remain lit.

`currentlyPlaying` returns `onState`, `color`, `pattern`, `architectural` and
`playlist`, with at most one of the last three active. Pattern bodies come from
the `patternData` object in `/folders/pattern/list`. Design bodies come from
`/deviceControl/architectural/list` with `preview: false` added.
