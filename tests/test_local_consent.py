"""Changing the controller's local-command setting requires explicit consent."""

import logging

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemstone_lights.coordinator import GemstoneCoordinator


async def test_setup_and_options_default_to_no_controller_changes(
    hass, entry, enable_custom_integrations
):
    # Given the actual account and options forms shown by Home Assistant.
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}
    )
    cloud = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "cloud"}
    )
    options = await hass.config_entries.options.async_init(entry.entry_id)
    # Then neither form checks permission to change the controller by default.
    assert (
        cloud["data_schema"](
            {"email": "new@example.invalid", "password": "test-password"}
        )["enable_local"]
        is False
    )
    assert options["data_schema"]({})["enable_local"] is False


@pytest.mark.parametrize("permission", [None, False, True])
async def test_account_setup_changes_controller_only_with_explicit_permission(
    hass, vendor, cognito_external, enable_custom_integrations, caplog, permission
):
    # Given a controller with local commands disabled in the vendor app.
    vendor.devices[0]["hub"] = {"localIp": "192.0.2.10", "tcpEnabled": False}
    caplog.set_level(logging.INFO, logger="custom_components.gemstone_lights")
    credentials = {"email": "new@example.invalid", "password": "test-password"}
    submitted = dict(credentials)
    if permission is not None:
        submitted["enable_local"] = permission
    # When account setup receives an omitted, unchecked, or checked permission.
    result = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}, data=submitted
    )
    await hass.async_block_till_done()
    entry = result["result"]
    try:
        coordinator = entry.runtime_data
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        await coordinator.async_refresh()
        settings_writes = [
            write
            for write in vendor.writes
            if write[2] == "/deviceControl/deviceSettings"
        ]
        if permission is True:
            assert settings_writes == [
                ("cloud", "hub", "/deviceControl/deviceSettings", {"tcpEnabled": True})
            ]
            assert coordinator.is_local("hub")
        else:
            assert vendor.writes == []
            assert not coordinator.is_local("hub")
            assert "'Allow Local Commands' is off, using cloud" in caplog.text
        assert entry.data == credentials
        assert entry.options == {"enable_local": permission is True}
        # Then normal light services still work using the permitted transport.
        entity_id = er.async_get(hass).async_get_entity_id(
            "light", "gemstone_lights", "hub_light"
        )
        await hass.services.async_call(
            "light", "turn_off", {"entity_id": entity_id}, blocking=True
        )
        assert vendor.writes[-1][0] == ("local" if permission is True else "cloud")
        assert vendor.states["hub"]["onState"] is False
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize("permission", [None, False, True])
async def test_options_permission_survives_reload_and_reauthentication(
    hass, vendor, cognito_external, enable_custom_integrations, permission
):
    # Given an account that previously opted in and an already-enabled controller.
    vendor.devices[0]["hub"] = {"localIp": "192.0.2.10", "tcpEnabled": True}
    entry = MockConfigEntry(
        domain="gemstone_lights",
        version=1,
        minor_version=2,
        data={"email": "test@example.invalid", "password": "test-password"},
        unique_id="test@example.invalid",
        options={"enable_local": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    try:
        before = entry.runtime_data
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        submitted = {} if permission is None else {"enable_local": permission}
        await hass.config_entries.options.async_configure(flow["flow_id"], submitted)
        await hass.async_block_till_done()
        assert entry.options["enable_local"] is (permission is True)
        assert entry.runtime_data is not before
        assert vendor.writes == []
        assert entry.runtime_data.is_local("hub")
        # When credentials change, the same consent choice survives another reload.
        before = entry.runtime_data
        flow = await hass.config_entries.flow.async_init(
            "gemstone_lights",
            context={"source": "reauth", "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"password": "new-test-password"}
        )
        await hass.async_block_till_done()
        assert result["reason"] == "reauth_successful"
        assert entry.runtime_data is not before
        assert entry.options["enable_local"] is (permission is True)
        # Then a newly discovered disabled controller is only enabled with consent.
        vendor.devices[0]["hub"]["tcpEnabled"] = False
        entry.runtime_data._discovery_next = None
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert vendor.writes == (
            [("cloud", "hub", "/deviceControl/deviceSettings", {"tcpEnabled": True})]
            if permission is True
            else []
        )
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize("legacy_permission", [None, False, True])
async def test_upgrade_requires_fresh_consent_and_preserves_other_settings(
    hass, vendor, cognito_external, enable_custom_integrations, legacy_permission
):
    # Given an older entry whose saved permission could have been an old default.
    vendor.devices[0]["hub"] = {"localIp": "192.0.2.10", "tcpEnabled": False}
    data = {
        "email": "test@example.invalid",
        "password": "test-password",
        "previous_metadata": {"keep": "this"},
    }
    options = {
        "enable_library": False,
        "recovery_delay_minutes": 25,
        "prefer_local": True,
    }
    if legacy_permission is not None:
        options["enable_local"] = legacy_permission
    entry = MockConfigEntry(
        domain="gemstone_lights",
        version=1,
        minor_version=1,
        data=data,
        unique_id="test@example.invalid",
        options=options,
    )
    entry.add_to_hass(hass)
    # When Home Assistant loads and migrates the account.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    try:
        # Then only the ambiguous permission resets; migration sends no setting writes.
        assert entry.minor_version == 2
        assert entry.data == data
        assert entry.options == {**options, "enable_local": False}
        assert vendor.writes == []
        assert not entry.runtime_data.is_local("hub")
        entity_id = er.async_get(hass).async_get_entity_id(
            "light", "gemstone_lights", "hub_light"
        )
        await hass.services.async_call(
            "light", "turn_off", {"entity_id": entity_id}, blocking=True
        )
        assert vendor.writes[-1][0] == "cloud"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_coordinator_default_never_enables_controller(hass, entry, api, vendor):
    # Given a coordinator created without an explicit local-setting permission.
    vendor.devices[0]["hub"] = {"localIp": "192.0.2.10", "tcpEnabled": False}
    coordinator = GemstoneCoordinator(hass, entry, api, enable_library=False)
    try:
        await coordinator._async_setup()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        # Then default polling never modifies the controller, and cloud commands work.
        assert vendor.writes == []
        assert not coordinator.is_local("hub")
        await coordinator.async_set_power("hub", False)
        assert vendor.writes[-1][0] == "cloud"
    finally:
        await coordinator.async_shutdown()
