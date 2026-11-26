"""Opt-in local recovery: restart a controller's LAN port through the account."""

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.gemstone_lights import coordinator as coordinator_module

from .test_cloud_option import CREDENTIALS, options_step


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: now[0])
    for name in (
        "LOCAL_RECOVERY_TOGGLE_DELAY",
        "LOCAL_RECOVERY_RETRY_DELAY",
        "LOCAL_RECOVERY_VERIFY_DELAY",
    ):
        monkeypatch.setattr(coordinator_module, name, 0)
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


@pytest.fixture
def restarts(hass):
    events = []
    hass.bus.async_listen(
        "gemstone_lights_local_restart", lambda event: events.append(event.data)
    )
    return events


async def refuse_for_five_minutes(hass, entry, vendor, clock):
    await options_step(hass, entry, "recovery", {"local_recovery": True, **CREDENTIALS})
    coordinator = entry.runtime_data
    vendor.refused = True
    await poll(hass, coordinator)
    clock[0] += 301
    await poll(hass, coordinator)
    return coordinator


async def test_a_restart_announces_its_result(
    hass, entry, loaded_entry, vendor, cognito_external, clock, restarts
):
    # Given local recovery is on and the LAN port refuses.
    # When the controller is restarted and its port opens again.
    await refuse_for_five_minutes(hass, entry, vendor, clock)
    # Then an event reports the restart for the controller's light.
    assert restarts == [
        {
            "device_id": "hub",
            "entity_id": "light.house",
            "name": "House",
            "result": "restarted",
            "error": None,
        }
    ]


async def test_switching_local_back_on_is_retried(
    hass, entry, loaded_entry, vendor, cognito_external, clock, restarts
):
    # Given switching Allow Local Commands on fails twice.
    vendor.enable_failures = 2
    # When the controller is restarted.
    await refuse_for_five_minutes(hass, entry, vendor, clock)
    # Then the third attempt switches it on and the restart succeeds.
    assert toggles(vendor) == [False, True, True, True]
    assert restarts[-1]["result"] == "restarted"
    assert not ir.async_get(hass).issues


async def test_local_left_off_raises_a_repair_and_retries_sooner(
    hass, entry, loaded_entry, vendor, cognito_external, clock, restarts
):
    # Given Allow Local Commands cannot be switched back on.
    vendor.enable_failures = 3
    # When the controller is restarted.
    coordinator = await refuse_for_five_minutes(hass, entry, vendor, clock)
    # Then the owner is told it was left off.
    assert restarts[-1]["result"] == "local_left_off"
    assert ("gemstone_lights", "local_left_off_hub") in ir.async_get(hass).issues
    # And it is tried again after ten minutes, not an hour.
    clock[0] += 599
    await poll(hass, coordinator)
    assert toggles(vendor) == [False, True, True, True]
    clock[0] += 2
    await poll(hass, coordinator)
    assert toggles(vendor)[-2:] == [False, True]
    assert restarts[-1]["result"] == "restarted"
    # And the repair goes away once the LAN answers again.
    await poll(hass, coordinator)
    assert ("gemstone_lights", "local_left_off_hub") not in ir.async_get(hass).issues


async def test_a_refused_account_request_raises_a_login_repair(
    hass, entry, loaded_entry, vendor, cognito_external, clock, restarts
):
    # Given the account refuses the request outright.
    vendor.enable_failures = 2
    vendor.settings_status = 403
    # When the controller would be restarted.
    await refuse_for_five_minutes(hass, entry, vendor, clock)
    # Then nothing was switched off and the owner is asked to check the login.
    assert restarts[-1]["result"] == "failed"
    issues = ir.async_get(hass).issues
    assert ("gemstone_lights", "recovery_login") in issues
    assert ("gemstone_lights", "local_left_off_hub") not in issues
