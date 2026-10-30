"""Local content edits must survive refreshes and drive real HA entities."""

from copy import deepcopy

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.gemstone_lights.coordinator import GemstoneCoordinator


def controller_entity(hass):
    return er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )


async def test_saved_pattern_survives_refresh_and_restart(
    hass, entry, loaded_entry, vendor
):
    # Given a local two-color pattern saved through the public HA action.
    light = controller_entity(hass)
    await hass.services.async_call(
        "gemstone_lights",
        "save_content",
        {
            "controller": light,
            "kind": "pattern",
            "name": "Local holiday",
            "content": {"colors": [255, 65280], "animation": "chase", "speed": 42},
        },
        blocking=True,
    )
    # When a poll runs, the entry reloads, and the pattern is selected.
    await loaded_entry.async_refresh()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    select = er.async_get(hass).async_get_entity_id(
        "select", "gemstone_lights", "hub_pattern"
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select, "option": "Local holiday"},
        blocking=True,
    )
    # Then the saved palette, speed and animation reach the controller intact over LAN.
    assert vendor.writes[-1][0] == "local"
    assert vendor.states["hub"]["pattern"]["colors"] == [255, 65280]
    assert vendor.states["hub"]["pattern"]["speed"] == 42
    assert vendor.states["hub"]["pattern"]["animation"] == "chase"


async def test_catalog_export_import_preserves_design_zone_references(
    hass, entry, loaded_entry
):
    # Given a local design referencing an existing zone.
    await loaded_entry.catalog.save(
        "hub",
        "design",
        "Front green",
        {
            "zonePatterns": [
                {
                    "zoneId": "front",
                    "pattern": {"colors": [65280], "animation": "motionless"},
                }
            ]
        },
    )
    exported = await hass.services.async_call(
        "gemstone_lights",
        "export_catalog",
        {"controller": controller_entity(hass)},
        blocking=True,
        return_response=True,
    )
    # When that export is imported into a fresh offline coordinator.
    fresh = GemstoneCoordinator(hass, entry)
    await fresh.catalog.import_data("hub", exported)
    # Then designs retain their zone references, zones keep geometry .
    assert fresh.designs("hub")[0]["zonePatterns"][0]["zoneId"] == "front"
    assert fresh.zone_ranges("hub") == {"front": (10, 12), "back": (13, 15)}
    assert "devices" not in exported
    await fresh.async_shutdown()


@pytest.mark.parametrize(
    "invalid", [{"colors": [-1]}, {"colors": [255], "backgroundColor": -1}]
)
async def test_invalid_import_is_atomic(coordinator, invalid):
    # Given existing local content and an import with a valid first item but invalid second item.
    await coordinator.catalog.save("hub", "pattern", "Keep", {"colors": [255]})
    before = deepcopy(coordinator.catalog.data)
    # When the import contains an out-of-range palette or background color.
    with pytest.raises(HomeAssistantError, match="Invalid catalog"):
        await coordinator.catalog.import_data(
            "hub",
            {
                "version": 1,
                "patterns": [
                    {"name": "New", "data": {"colors": [65280]}},
                    {"name": "Broken", "data": invalid},
                ],
            },
        )
    # Then no part of the import replaces or adds to the existing catalog.
    assert coordinator.catalog.data == before


async def test_local_zone_entity_controls_only_its_pixel_range(
    hass, loaded_entry, vendor
):
    # Given a newly created local zone outside the existing front/back ranges.
    await hass.services.async_call(
        "gemstone_lights",
        "save_content",
        {
            "controller": controller_entity(hass),
            "kind": "zone",
            "name": "Porch",
            "content": {"start": 20, "end": 22},
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    zone_id = next(z["id"] for z in loaded_entry.zones("hub") if z["name"] == "Porch")
    entity = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", f"hub_zone_{zone_id}"
    )
    vendor.states["hub"] = {"onState": False}
    await loaded_entry.async_refresh()
    # When the new zone is turned green through Home Assistant.
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity, "rgbw_color": [0, 255, 0, 0]},
        blocking=True,
    )
    # Then the LAN command lights precisely the three selected pixels.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": [20, 21, 22], "color": 65280}
    ]


async def test_overlapping_zone_edit_leaves_catalog_unchanged(coordinator):
    # Given front and back zones already cover pixels 10 through 15.
    before = deepcopy(coordinator.catalog.data)
    # When a new zone overlaps the existing front range.
    with pytest.raises(HomeAssistantError, match="overlaps Front"):
        await coordinator.catalog.save(
            "hub", "zone", "Collision", {"start": 11, "end": 20}
        )
    # Then no ambiguous zone definition is stored.
    assert coordinator.catalog.data == before


@pytest.mark.parametrize("direction", [0, 5])
async def test_custom_zone_action_completes_native_pattern_fields(
    hass, loaded_entry, vendor, direction
):
    # Given an existing controller zone and a short custom palette with a vendor direction value.
    zone = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_zone_front"
    )
    # When the user plays it without supplying firmware identity fields.
    await hass.services.async_call(
        "gemstone_lights",
        "play_content",
        {
            "entity_id": zone,
            "kind": "pattern",
            "content": {
                "colors": [65280, 0],
                "animation": "chase",
                "direction": direction,
                "brightness": 80,
            },
        },
        blocking=True,
    )
    # Then the firmware accepts the completed pattern and preserves its palette, orientation and level.
    patterns = {
        z["zoneId"]: z["pattern"]
        for z in vendor.states["hub"]["architectural"]["zonePatterns"]
    }
    assert patterns["front"]["colors"] == [65280, 0]
    assert patterns["front"]["direction"] == direction
    assert patterns["front"]["brightness"] == 80
    assert patterns["back"]["colors"] == [255]
