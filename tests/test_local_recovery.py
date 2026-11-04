"""Opt-in local recovery: restart a controller's LAN port through the account."""

import pytest

from custom_components.gemstone_lights import coordinator as coordinator_module

from .test_cloud_option import CREDENTIALS, options_step


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: now[0])
    monkeypatch.setattr(coordinator_module, "LOCAL_RECOVERY_TOGGLE_DELAY", 0)
    return now


def toggles(vendor):
    return [
        w[3]["tcpEnabled"]
        for w in vendor.writes
        if w[2] == "/deviceControl/deviceSettings"
    ]


async def poll(hass, coordinator):
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_refused_port_is_restarted_once_after_five_minutes(
    hass, entry, loaded_entry, vendor, cognito_external, clock
):
    # Given local recovery is on and the controller's LAN port refuses.
    await options_step(hass, entry, "recovery", {"local_recovery": True, **CREDENTIALS})
    coordinator = entry.runtime_data
    assert coordinator.api is None
    vendor.refused = True
    # When it has refused for under five minutes, nothing is sent.
    await poll(hass, coordinator)
    clock[0] += 299
    await poll(hass, coordinator)
    assert toggles(vendor) == []
    # Then after five minutes Allow Local Commands is switched off and on.
    clock[0] += 2
    await poll(hass, coordinator)
    assert toggles(vendor) == [False, True]
    assert coordinator.health("hub")["local_restarts"] == 1
    # And the next poll reads the controller over LAN again.
    await poll(hass, coordinator)
    assert coordinator.is_local("hub")
    assert vendor.writes[-1][0] == "cloud"
    assert all(w[2] == "/deviceControl/deviceSettings" for w in vendor.writes)


async def test_restart_is_not_repeated_within_an_hour(
    hass, entry, loaded_entry, vendor, cognito_external, clock
):
    # Given a restart did not bring the port back.
    await options_step(hass, entry, "recovery", {"local_recovery": True, **CREDENTIALS})
    coordinator = entry.runtime_data
    vendor.refused = True
    await poll(hass, coordinator)
    clock[0] += 301
    await poll(hass, coordinator)
    vendor.refused = True
    # When it keeps refusing for most of an hour, no second restart is sent.
    clock[0] += 3500
    await poll(hass, coordinator)
    assert toggles(vendor) == [False, True]
    # Then one more is allowed after the hour.
    clock[0] += 101
    await poll(hass, coordinator)
    assert toggles(vendor) == [False, True, False, True]


async def test_timeouts_never_trigger_a_restart(
    hass, entry, loaded_entry, vendor, cognito_external, clock
):
    # Given local recovery is on and the controller fails without refusing.
    await options_step(hass, entry, "recovery", {"local_recovery": True, **CREDENTIALS})
    coordinator = entry.runtime_data
    vendor.failures["/device-state/currently-playing"] = 500
    # When it fails for longer than five minutes.
    await poll(hass, coordinator)
    clock[0] += 600
    await poll(hass, coordinator)
    # Then the account is not used.
    assert toggles(vendor) == []


async def test_without_the_option_a_refused_port_never_uses_the_account(
    hass, loaded_entry, vendor, clock
):
    vendor.refused = True
    await poll(hass, loaded_entry)
    clock[0] += 600
    await poll(hass, loaded_entry)
    assert vendor.writes == []


async def test_turning_recovery_off_deletes_credentials_unless_cloud_is_on(
    hass, entry, loaded_entry, vendor, cognito_external
):
    await options_step(hass, entry, "recovery", {"local_recovery": True, **CREDENTIALS})
    assert entry.options["password"] == "test-password"
    assert entry.runtime_data.recovery_api is not None
    await options_step(hass, entry, "recovery", {"local_recovery": False})
    assert "password" not in entry.options and "email" not in entry.options
    assert entry.runtime_data.recovery_api is None
    # With cloud access on, turning recovery off keeps the shared credentials.
    await options_step(hass, entry, "cloud", {"cloud_access": True, **CREDENTIALS})
    await options_step(hass, entry, "recovery", {"local_recovery": True})
    await options_step(hass, entry, "recovery", {"local_recovery": False})
    assert entry.options["password"] == "test-password"
    # And turning cloud access off keeps them while recovery is on.
    await options_step(hass, entry, "recovery", {"local_recovery": True})
    await options_step(hass, entry, "cloud", {"cloud_access": False})
    assert entry.options["password"] == "test-password"
    assert entry.runtime_data.api is None
    assert entry.runtime_data.recovery_api is not None
