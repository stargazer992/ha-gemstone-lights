"""Exactly one regression for each designated release edge case."""

import asyncio

from homeassistant.helpers import entity_registry as er


async def test_edge_case_a_offline_restart(hass, entry, loaded_entry, vendor):
    # Given a previously working installation with persisted discovery and catalog data.
    await loaded_entry.async_play_color("hub", 4278190080, 80)
    await hass.config_entries.async_unload(entry.entry_id)
    vendor.cloud_offline = True
    # When HA recreates the integration with a fresh coordinator while the internet is down.
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )
    restored = hass.states.get(entity_id)
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    # Then state/brightness survive startup and commands still reach the local controller.
    assert entry.runtime_data is not loaded_entry
    assert restored.state == "on"
    assert restored.attributes["rgbw_color"] == (253, 244, 188, 0)  # Warm White
    assert restored.attributes["brightness"] == 80
    assert vendor.writes[-1][0] == "local"
    assert not vendor.states["hub"]["onState"]


async def test_edge_case_b_simultaneous_zone_edits(coordinator, vendor):
    # Given controller echo lag and two distinct zone edits dispatched concurrently.
    vendor.echo_writes = False
    vendor.first_write_started = asyncio.Event()
    vendor.release_first_write = asyncio.Event()
    coordinator.data["devices"]["hub"]["state"] = {"onState": False}
    # When both complete through the real per-controller command queue.
    tasks = [
        asyncio.create_task(
            coordinator.async_set_zone(
                "hub", "front", {"color": 255, "brightness": 80, "animation": "Solid"}
            )
        ),
        asyncio.create_task(
            coordinator.async_set_zone(
                "hub", "back", {"color": 65280, "brightness": 200, "animation": "chase"}
            )
        ),
    ]
    await vendor.first_write_started.wait()
    await asyncio.sleep(0)
    vendor.release_first_write.set()
    await asyncio.gather(*tasks)
    # Then the final replacement design contains both requested changes, despite stale state.
    patterns = {
        entry["zoneId"]: entry["pattern"]
        for entry in vendor.writes[-1][3]["architectural"]["zonePatterns"]
    }
    assert set(patterns) == {"front", "back"}
    assert patterns["front"]["colors"] == [255]
    assert patterns["front"]["brightness"] == 80
    assert patterns["back"]["colors"] == [65280]
    assert patterns["back"]["brightness"] == 200
    assert patterns["back"]["animation"] == "chase"
