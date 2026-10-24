# Development and testing

The supported and tested baseline is Home Assistant **2026.9.1**, on Python **3.14.2 or newer within 3.14**.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.lock
.venv/bin/python -m pytest
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

CI runs these checks alongside HACS and hassfest. Dependency versions are pinned in
`requirements-test.lock`. Update the direct versions in `requirements-test.txt`,
then regenerate the cross-platform lock with:

```sh
uv pip compile requirements-test.txt --universal --python-version 3.14.2 -o requirements-test.lock
```

## Test standards

- Use explicit **Given / When / Then** sections in every test.
- Assert observable behavior, transformed payloads, state reconciliation, and errors
  that affect the user. Do not test language primitives or repeat a mock's configured
  return value as the only assertion.
- Run real integration logic and Home Assistant entities. Mock only external I/O:
  HTTP requests, Cognito SDK operations, and Home Assistant's storage fixture. Do not
  patch coordinator methods, payload builders, or other business-logic helpers.
- Network sockets are blocked during tests. The external vendor fixture can delay
  or reject HTTP responses, so tests can reproduce actual concurrency and outage
  scenarios without real credentials or hardware.
- `tests/test_edge_cases.py` contains exactly one dedicated test for each designated
  release scenario: **A**, integration startup after restart with cloud access down;
  **B**, simultaneous edits to two zones while the first network write is held and
  cloud state echoes lag.
- The Home Assistant test fixtures verify cleanup; delayed refreshes and platform
  listeners must not leak after unloading.

The HTTP fixture includes a small compatibility adapter because aioresponses 0.7.9
does not yet supply aiohttp 3.14's `stream_writer` constructor argument. This adapts
the external response object and does not replace any integration logic.

## Controller smoke test

Automated tests exercise the documented protocol through simulated external I/O;
they do not establish that a particular firmware implements it correctly. Before
reporting a hardware regression fixed, check the affected operation on a Hub2:
power, RGBW color, dim/brighten, two-zone edits, whole-design dimming, saved patterns,
and cloud-only fallback. For offline startup, first allow one successful online
discovery with local control enabled, then restart Home Assistant while cloud access
is unavailable. A changed DHCP address still requires discovery or a corrected
controller-specific address override.

Keep fixes and their regression tests in separate logical commits. Preserve those
commits when merging a release PR.

## Protocol references

- [Hub2 API reference](PROTOCOL.md): LAN and cloud requests, colour encoding,
  patterns and designs.
- [Bluetooth protocol](BLUETOOTH_PROTOCOL.md): local Bluetooth transport.
- [Native management](MANAGEMENT_PROTOCOL.md): zone, timer and device settings
  research, including features not implemented by the integration.
- [Repository review](REVIEW.md): implementation findings and fixes.
