# Recovering a failed local service

A Hub2 can remain cloud-controllable while its HTTP service stops accepting LAN
connections. Issue #7 reports recovery after a controller power cycle; the owner's
HA logs also showed connection failure and HTTP 500, and the owner recovered the
service with the vendor app's Soft Reboot action. The firmware failure's cause is
unknown. Reboot recovery does not establish that polling caused or fixed it.

## Cloud fallback

For an account-based entry, uncheck **Disable all Gemstone cloud access** and keep
**Use local control when available** enabled. HA then uses cloud reads and writes
when LAN fails. Without automatic recovery, it retries LAN after five minutes.
Strict local-only mode deliberately becomes unavailable when its local route
fails; it never contacts the cloud, even if an automatic-recovery preference was
previously saved. A controller added without an account has no cloud credentials.

## Manual soft reboot

An HA administrator can run this action even while the light is unavailable:

```yaml
action: gemstone_lights.soft_reboot
data:
  controller: light.your_controller
```

It requires a working cloud account and fresh discovery reporting that controller
online in the account. Requests are serialized per controller and duplicate
requests within two minutes are rejected. The action returns when the cloud
request succeeds, not when the controller has restarted. Allow about one minute
for the reboot; LAN probes resume after a 90-second grace period. Lighting state
is not replaced or replayed by this action.

## Optional automatic recovery

Enable **Automatically soft reboot after persistent LAN failure** in Configure.
It is off by default. The default failure duration is 10 minutes (configurable
5–60); the cooldown is six hours (configurable 1–168).

Recovery requires all of the following:

- At least three failed LAN state probes against the same address, spanning the
  configured failure duration. With recovery enabled, failed LAN probes are
  retried at one-minute intervals; ordinary cloud polling remains unchanged.
- Successful cloud state access and fresh account discovery reporting the same
  controller online, with local commands enabled and the same LAN address.
- No previous automatic attempt in this outage unless an administrator has
  explicitly re-armed recovery, and expiry of the cooldown from any previous
  manual or automatic attempt.

One attempt is allowed per uninterrupted outage unless explicitly re-armed. An
HTTP error or lost response consumes that attempt too: repeating an uncertain
reboot could cause a loop. The attempt is stored **before** the request and
survives integration reloads and HA restarts. A successful local state read ends
the outage, but does not clear the cooldown. If storage cannot persist the
attempt, no reboot is sent.

Automatic recovery never reacts to Bluetooth failures, disabled local commands,
a changed cloud-reported IP address, unavailable cloud authentication, or strict
local-only operation. It does not factory-reset or modify Wi-Fi credentials.
Cloud online status is vendor-reported, not independent proof of physical
reachability. If a reboot fails to restore LAN, investigate the controller and
network rather than automatically rebooting it again.

## Re-arming automatic recovery

After investigating an unsuccessful automatic attempt, an HA administrator can
allow another attempt for that controller in **Developer tools → Actions**:

```yaml
action: gemstone_lights.rearm_recovery
data:
  controller: light.your_controller
```

Select the whole-controller light, even if it is unavailable. Re-arming clears
the stored per-outage attempt limit and starts a fresh failure observation
window. It preserves the previous attempt timestamp and the full configured
cooldown, and survives integration reloads and HA restarts. If the update cannot
be saved, the action fails without clearing the limit.

Automatic recovery must already be enabled in Configure. The next automatic
attempt still requires at least three new failed LAN probes spanning the
configured failure duration, expiry of the remaining cooldown, and successful
cloud checks. Re-arming does not immediately reboot the controller, send a
controller command, enable automatic recovery, or change Allow Local Commands.
Use the separate **Soft reboot controller** action when you want an immediate
manual reboot.

## Recovery status

The **Now playing** sensor exposes these attributes for troubleshooting and
automations:

| Attribute | Meaning |
| --- | --- |
| `recovery_status` | Current recovery condition, described below. |
| `recovery_last_attempt` | UTC timestamp of the last manual or automatic reboot attempt, or `null`. |
| `recovery_cooldown_until` | UTC timestamp when the cooldown from that attempt ends, or `null`. |
| `recovery_failure_since` | UTC timestamp of the first failure in the current observation window, or `null`. |
| `recovery_failed_probes` | Number of failed LAN probes in that window. |

Useful `recovery_status` values include:

| Status | Meaning |
| --- | --- |
| `local_available` | The latest LAN state read succeeded. |
| `monitoring` | Recovery is enabled and waiting for evidence of a persistent LAN failure. |
| `waiting` | LAN failures have not yet met the probe count or duration threshold. |
| `cooldown` | The minimum time since the last reboot attempt has not elapsed. |
| `exhausted` | This outage has consumed its automatic attempt; a successful LAN read or an explicit re-arm clears the limit. |
| `ready` | The observed failure threshold and cooldown permit an attempt, subject to fresh cloud discovery checks. |
| `disabled` | Automatic recovery is turned off. |
| `cloud_unavailable` | Cloud access is unavailable, so recovery cannot proceed. |

Other statuses explain ineligible configurations: `local_only`,
`local_not_preferred`, `bluetooth`, and `local_commands_disabled`. The last refers
to the controller's reported Allow Local Commands setting, not the integration's
separate automatic-enable preference. A status describes the current condition;
it does not prove that a reboot request will succeed or restore local service.

## Protocol evidence

The Android app 0.6.64 generated the following request during an intercepted
Soft Reboot confirmation on 2026-09-17. The capture proxy blocked the request
before forwarding it, and emulator networking was restored afterward:

```http
POST /prod/deviceControl/softReboot?deviceId=<controller>&homegroupId=<homegroup>
Authorization: Bearer <account access token>
```

The body was empty. This POST is an exception to the lighting API's PUT routes.
The integration resolves the homegroup through fresh discovery; it does not
hard-code an owner's identifiers. Authentication and transport errors are
surfaced, and the reboot request is not automatically retried even on an HTTP
401/403. LAN readback, rather than HTTP acceptance alone, establishes recovery.

## Physical validation

On the owner's Hub2 firmware 1.1.5, the candidate HA action returned HTTP 200.
An independent LAN monitor observed the local API become unreachable and then
return after approximately 19 seconds. The entire reported playing state matched
the pre-test state exactly; no lighting restoration write was needed. This
verifies the manual cloud command and reboot cycle. The automatic failure policy
is exercised through simulated external I/O, not by deliberately crashing the
controller's HTTP service.
