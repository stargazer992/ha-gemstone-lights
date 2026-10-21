# Changelog

## 1.8.1 — Unreleased

- Require an explicit, unchecked-by-default opt-in before account mode enables
  "Allow Local Commands" on controllers. Setup and options explain that this
  exposes unauthenticated HTTP control on the LAN.
- Reset the previous automatic-enable preference during upgrade because older
  versions preselected it. Users can opt in again in Configure; the controller's
  current setting is left unchanged.
- Preserve LAN use for controllers already enabled and cloud control when local
  commands are disabled. Local-only and Bluetooth behavior remain unchanged.

## 1.8.0

- Add an administrator soft-reboot action using the app's captured cloud POST protocol.
- Add opt-in recovery after sustained LAN failure, with fresh cloud checks, one attempt per outage, a persistent cooldown, and a reboot grace period.
- Keep strict local-only mode free of cloud requests and preserve lighting content during recovery.
- Expand functional tests for LAN refusal/timeouts, cloud fallback, reboot guards, failed responses, reload persistence and configuration.


## 1.7.1 — 2026-09-06

- Decode native zone selections as explicit pixels and compressed inclusive runs,
  preserving single-pixel, short and noncontiguous layouts throughout rendering,
  readback, neighboring-zone preservation and overlap validation.
- Repeat static palettes across selected pixels without filling unselected gaps.
- Compare complete native selections before animated playback; matching final
  endpoints no longer hides a resized HA override. Reject unusable geometry
  before either local or cloud commands can be sent.
- Migrate older HA-created count/start/end catalog records while keeping zone IDs.
  Portable catalog version 2 stores explicit selections and preserves gaps.
  Identifiable version 1 local ranges remain importable; ambiguous unmarked old
  exports are rejected with a re-export instruction rather than guessed.
- Add 27 functional geometry and catalog regressions. Six control regressions
  were confirmed to fail against the previous coordinator. The mixed compressed
  format was independently checked in the offline vendor app.


## 1.7.0 — 2026-09-06

- Add optional account-free Bluetooth setup and an address override for existing
  controllers, preserving entity IDs, zones and cached catalogs when switching.
- Implement verified Hub2 firmware, playing-state and settings reads plus desired
  state writes, with MTU-aware fragmentation and application acknowledgments.
- Use HA's connectable Bluetooth adapters/proxies and release connections after
  each operation. Keep strict local-only operation available without credentials.
- Surface explicit controller rejection without cloud replay or false disconnect.
- Add 27 Bluetooth transport and HA behavior tests covering malformed/incomplete
  replies, rejection, timeouts, disconnects, concurrency and transport migration.
- Document physical firmware 1.1.5 validation, content normalization limits and
  captured music packets. Music playback, native timer editing, protected firmware
  and factory-new provisioning remain unresolved.

## 1.6.0 — 2026-09-06

- Add account-free setup by LAN address and an explicit option that disables all
  cloud authentication, discovery, catalog refreshes and command fallback.
- Add local pattern/design/zone editing, current-content saving, custom playback,
  portable catalog import/export and protection from cloud catalog overwrites.
- Render existing native animated zones over LAN on verified Hub2 firmware 1.1.5.
  Direct controller commands and timed camera frames confirmed chase movement.
- Expand motionless zone palettes into explicit pixels, supporting new HA-only
  static zones. Reject new/resized native animated zones until a zone-definition
  management protocol is verified.
- Provide HA script/automation blueprints for playlists, weekly schedules and
  sunset-to-sunrise operation, tested in the real HA automation engine.
- Request separate HTTP connections to avoid observed embedded-server stalls.
- Fill in firmware-required identity/default fields for custom content and retain
  all six direction values observed in the live vendor catalog.
- Document a complete capability inventory and unresolved provisioning, music,
  firmware, settings and native schedule/playlist management protocols. This is
  not a claim of complete offline parity with every function in the vendor app.
- Extend the behavior suite to 71 tests with functional Given/When/Then assertions.

## 1.5.2 — 2026-09-06

- Retain logical zone colors and brightness after master dimming through the
  cloud. Hub2 copies the master level into each nested pattern's reported
  brightness; reconcile that redundant field without treating it as another
  brightness multiplier or losing the original palette.
- Extend the hardware-derived regression to poll after master dimming before
  brightening again. It reproduces the incorrect zone levels on 1.5.1.

## 1.5.1 — 2026-09-06

- Correct independent brightness for animated zones sent through the cloud. Live
  testing on Hub2 firmware 1.1.5 found that cloud playback resets each nested
  pattern's brightness to the master level (255 at full brightness). Encode
  independent dimming in every RGBW palette and
  background color while retaining the logical color and level in Home Assistant.
- Preserve those logical zone values through normalized controller echoes, local
  write failures, cloud power changes, and repeated dim/brighten operations.
- Schedule the command follow-up poll after the five-second optimistic-state
  window so accepted but unapplied commands are detected promptly.
- Add hardware-derived HTTP response normalization and four behavior regressions.
  The cloud brightness and refresh regressions were first verified to fail against
  the previous behavior.

Live validation of 1.5.0 confirmed power, red/white output, dim/brighten, simultaneous
zone edits, neighboring-zone preservation, saved designs and patterns, and zone
state persistence through an integration reload. It also exposed the cloud-zone
brightness issue corrected here. A full restart with the internet disconnected
remains covered by automated tests rather than a live outage drill.

## 1.5.0 — 2026-09-06

Requires Home Assistant **2026.9.1 or later**; the supported baseline is raised
from 2024.12. This release adds persistent offline recovery and corrects controller,
zone, authentication, and entity behavior identified in the 1.4.4 repository review.

- Restore known local controllers, zones, and cached catalogs after restarting
  without internet. Initial discovery and cloud-only features still need the cloud.
- Keep local lights usable during cloud outages and reauthentication. Report failed
  devices as unavailable without inventing off states.
- Serialize complete commands per controller, preserve neighboring zone palettes and
  metadata, retain both concurrent zone edits, and keep other zones on when one is
  switched off during whole-controller playback.
- Route designs according to local capabilities; preserve independent RGBW zone
  brightness and relative brightness when dimming a complete solid design offline.
- Decode three-pixel local layouts correctly and reject zone edits that would
  silently discard unrelated, unrepresentable pixel content.
- Preserve logical color/brightness through cloud dimming, controller echoes,
  power changes, and restarts; respect subsequently observed external changes.
- Bind address overrides to a selected controller and validate host input.
- Correct login error classification, token renewal, and bounded authentication
  retries. Validate vendor response shapes before rendering or editing state.
- Support zone-targeted library actions, discover new controllers on every platform,
  preserve complete catalogs on partial failures, and remove deleted patterns after
  successful empty refreshes.
- Keep off controllers off when speed changes. Track local-enable tasks through
  unload and allow retries after transient activation failures.
- Add pinned Home Assistant behavior tests, meaningful network-boundary regression
  tests, account-flow and lifecycle tests, and CI alongside HACS and hassfest.

Tests simulate external HTTP, authentication, and storage I/O. The two dedicated
edge-case regressions cover offline restart and simultaneous zone edits, and were
also verified to fail when their respective fixes were deliberately removed.
No live-controller smoke test was performed for this release.
