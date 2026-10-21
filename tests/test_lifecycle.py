"""Run discovery and service behavior through real Home Assistant platforms."""

from unittest.mock import patch

from botocore.exceptions import ClientError
from homeassistant.helpers import entity_registry as er


async def test_new_controller_gets_every_platform_without_reload(
    hass, loaded_entry, vendor
):
    # Given the integration is already loaded and another local controller is added.
    vendor.devices.append(
        {
            "id": "garage",
            "name": "Garage",
            "online": True,
            "hub": {"localIp": "192.0.2.11", "tcpEnabled": True},
        }
    )
    vendor.states["garage"] = {
        "onState": True,
        "colorB": {"value": 65280, "brightness": 80},
    }
    loaded_entry._discovery_next = None
    # When normal discovery refreshes and platform listeners process the new device.
    await loaded_entry.async_refresh()
    await hass.async_block_till_done()
    # Then all seven controller entities are registered and available without reloading.
    entities = [
        entity
        for entity in er.async_get(hass).entities.values()
        if entity.unique_id.startswith("garage_")
    ]
    assert {entity.unique_id for entity in entities} == {
        "garage_light",
        "garage_speed",
        "garage_now_playing",
        "garage_design",
        "garage_pattern",
        "garage_library_folder",
        "garage_library_pattern",
    }
    assert all(
        hass.states.get(entity.entity_id).state != "unavailable" for entity in entities
    )


async def test_registered_library_service_respects_zone_entity_target(
    hass, loaded_entry, vendor
):
    # Given real registered zone entities and a cached library pattern.
    front = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_zone_front"
    )
    # When Home Assistant dispatches the public integration action to the front zone.
    await hass.services.async_call(
        "gemstone_lights",
        "play_library_pattern",
        {"entity_id": front, "pattern": "Holiday"},
        blocking=True,
    )
    # Then the complete palette reaches only the front zone and the back stays red.
    entries = {
        e["zoneId"]: e["pattern"]
        for e in vendor.writes[-1][3]["architectural"]["zonePatterns"]
    }
    assert entries["front"]["colors"] == [255, 65280]
    assert entries["back"]["colors"] == [255]


async def test_cloud_reauthentication_keeps_local_entities_operational(
    hass, loaded_entry, vendor
):
    # Given an already-loaded local controller whose cloud credentials are rejected.
    await loaded_entry.api.async_login()
    vendor.failures["/homegroup/list"] = 401
    loaded_entry._discovery_next = None
    rejection = ClientError(
        {"Error": {"Code": "NotAuthorizedException"}}, "InitiateAuth"
    )
    # When discovery exhausts authentication retry through the external Cognito SDK.
    with patch("botocore.client.BaseClient._make_api_call", side_effect=rejection):
        await loaded_entry.async_refresh()
        await hass.async_block_till_done()
    # Then HA asks for credentials once and the local light stays available and controllable.
    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    ]
    assert len(flows) == 1
    entity_id = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )
    assert hass.states.get(entity_id).state == "on"
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    assert vendor.writes[-1][0] == "local"
    assert not vendor.states["hub"]["onState"]


async def test_enabling_local_control_updates_cached_discovery_immediately(
    hass, entry, loaded_entry, vendor
):
    # Given discovery finds that local commands were disabled in the vendor app.
    vendor.devices[0]["hub"]["tcpEnabled"] = False
    loaded_entry._discovery_next = None
    await loaded_entry.async_refresh()
    await hass.async_block_till_done()
    assert vendor.writes == []
    # When the user explicitly opts in through HA's options form and it reloads.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enable_local": True}
    )
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    await coordinator.async_refresh()
    # Then the controller is used locally without waiting for cloud rediscovery or repeating the enable write.
    settings_writes = [
        write for write in vendor.writes if write[2] == "/deviceControl/deviceSettings"
    ]
    assert settings_writes == [
        ("cloud", "hub", "/deviceControl/deviceSettings", {"tcpEnabled": True})
    ]
    assert coordinator.is_local("hub")
