"""Offline setup and operation through HA's real config and entity lifecycle."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemstone_lights.coordinator import GemstoneCoordinator


async def test_local_setup_needs_no_account_or_cloud(
    hass, vendor, http, enable_custom_integrations
):
    # Given a provisioned LAN controller and no Gemstone credentials or Cognito mock.
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "local"}
    )
    # When it is added by address and its catalogs become due for refresh.
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"host": "192.0.2.10", "name": "Offline house"}
    )
    await hass.async_block_till_done()
    entry = result["result"]
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await coordinator.async_play_color("local:192.0.2.10", 65280, 80)
    # Then physical commands use LAN and no authentication/discovery/catalog URL is contacted.
    assert entry.data["local_only"] is True
    assert "password" not in entry.data
    assert coordinator.device_available("local:192.0.2.10")
    assert vendor.states["hub"]["colorB"] == {"value": 65280, "brightness": 80}
    assert {url.host for _, url in http.requests} == {"192.0.2.10"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_local_failure_reports_unavailable_then_recovers_without_cloud(
    hass, vendor, http
):
    # Given an offline-only controller whose LAN connection fails.
    entry = MockConfigEntry(
        domain="gemstone_lights",
        data={
            "local_device": {
                "id": "hub",
                "hub": {"localIp": "192.0.2.10", "tcpEnabled": True},
            }
        },
    )
    entry.add_to_hass(hass)
    coordinator = GemstoneCoordinator(hass, entry)
    await coordinator._async_setup()
    await coordinator.async_refresh()
    vendor.failures["/device-state/currently-playing"] = 503
    # When a poll fails and a command is attempted during the outage.
    await coordinator.async_refresh()
    vendor.failures["/device-control/play"] = 503
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await coordinator.async_set_power("hub", False)
    vendor.failures.pop("/device-control/play")
    # Then the entity is unavailable, no cloud is contacted, and the next successful poll recovers.
    assert not coordinator.device_available("hub")
    vendor.failures.clear()
    await coordinator.async_refresh()
    assert coordinator.device_available("hub")
    assert vendor.writes == []
    assert {url.host for _, url in http.requests} == {"192.0.2.10"}
    await coordinator.async_shutdown()


async def test_cloud_era_account_entry_migrates_to_local_with_cached_content(
    hass, vendor, http, hass_storage, config_dir, enable_custom_integrations
):
    # Given a version 1 account entry with credentials and an upstream-format cache.
    entry = MockConfigEntry(
        domain="gemstone_lights",
        version=1,
        minor_version=2,
        data={"email": "test@example.invalid", "password": "test-password"},
        options={"auto_recovery": True, "enable_library": True, "host": "192.0.2.10"},
        unique_id="test@example.invalid",
    )
    entry.add_to_hass(hass)
    key = f"gemstone_lights.{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "devices": vendor.devices,
            "zones": vendor.zones,
            "patterns": [
                {"folder": "Mine", "name": "Glamo WW", "data": {"colors": [255]}}
            ],
            "library": {"folder": [{"name": "Holiday", "data": {"colors": [255]}}]},
            "library_folders": {
                "folder": {
                    "id": "folder",
                    "folderName": "Christmas",
                    "category": "holidays",
                }
            },
            "speeds": {"hub": 42},
            "state_aliases": {"hub": {"logical": {}, "wire": {}}},
        },
    }
    # When Home Assistant loads it.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # Then credentials and cloud-only options are gone, content survives, and only LAN is used.
    assert entry.version == 2
    assert "password" not in entry.data and "email" not in entry.data
    assert entry.options == {"host": "192.0.2.10"}
    assert {zone["id"] for zone in coordinator.zones("hub")} == {"front", "back"}
    assert [p["name"] for p in coordinator.patterns()] == ["Glamo WW"]
    assert coordinator.find_library_pattern("Holiday") is not None
    assert (config_dir / "www" / "gemstones" / "index.json").exists()
    assert set(hass_storage[key]["data"]) == {
        "devices",
        "local_catalog",
        "zones",
        "designs",
        "patterns",
    }
    assert coordinator.device_available("hub")
    assert {url.host for _, url in http.requests} == {"192.0.2.10"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_local_setup_rejects_urls_before_network_io(
    hass, http, enable_custom_integrations
):
    # Given a local setup form with a URL where only an address is valid.
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "local"}
    )
    # When the invalid host is submitted.
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"host": "https://example.invalid/path"}
    )
    # Then the user gets a field error and nothing is sent to that URL.
    assert result["errors"] == {"host": "invalid_host"}
    assert http.requests == {}
