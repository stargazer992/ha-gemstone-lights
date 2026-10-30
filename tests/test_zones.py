"""Zone editing must preserve content outside the fields being changed."""

import asyncio
from copy import deepcopy

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.gemstone_lights.light import GemstoneZoneLight


async def test_editing_front_preserves_complete_back_pattern(coordinator, vendor):
    # Given the back zone has a multi-color pattern with vendor-specific settings.
    back = {
        "zoneId": "back",
        "vendorFlag": "keep",
        "pattern": {
            "id": "saved",
            "colors": [255, 65280],
            "animation": "chase",
            "speed": 17,
            "direction": 1,
            "brightness": 80,
            "backgroundColor": 4278190080,
            "vendorExtension": {"keep": 42},
        },
    }
    original = deepcopy(back)
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {"zonePatterns": [back]},
    }
    # When only the front zone is changed to blue.
    await coordinator.async_set_zone(
        "hub", "front", {"color": 16711680, "brightness": 200, "animation": "Solid"}
    )
    # Then the back zone is resent unchanged, metadata included, over LAN.
    sent = vendor.writes[-1][3]["architectural"]["zonePatterns"]
    assert next(e for e in sent if e["zoneId"] == "back") == original
    front = next(e for e in sent if e["zoneId"] == "front")["pattern"]
    assert (front["colors"], front["brightness"]) == ([16711680], 200)
    assert back == original


async def test_dimming_a_zone_keeps_its_palette_and_animation_settings(
    coordinator, vendor
):
    # Given a running two-color zone pattern.
    pattern = {
        "colors": [255, 65280],
        "animation": "chase",
        "speed": 17,
        "brightness": 200,
    }
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {"zonePatterns": [{"zoneId": "front", "pattern": pattern}]},
    }
    light = GemstoneZoneLight(coordinator, "hub", "front")
    # When only its brightness changes through the light entity.
    await light.async_turn_on(brightness=80)
    # Then only the zone's brightness changes; palette and animation survive.
    sent = vendor.writes[-1][3]["architectural"]["zonePatterns"][0]["pattern"]
    assert sent == {**pattern, "brightness": 80}
    assert coordinator.device_state("hub")["architectural"]["zonePatterns"][0][
        "pattern"
    ] == {**pattern, "brightness": 80}


async def test_turning_off_front_of_whole_run_preserves_back(coordinator, vendor):
    # Given the whole controller is playing a multi-color pattern.
    pattern = {
        "colors": [255, 65280],
        "animation": "chase",
        "speed": 17,
        "brightness": 200,
    }
    coordinator.data["devices"]["hub"]["state"] = {"onState": True, "pattern": pattern}
    front = GemstoneZoneLight(coordinator, "hub", "front")
    back = GemstoneZoneLight(coordinator, "hub", "back")
    # When only the front zone is switched off.
    await front.async_turn_off()
    # Then the controller stays on, the back keeps the full pattern, and the front is off.
    sent = vendor.writes[-1][3]["architectural"]["zonePatterns"]
    assert sent == [
        {
            "zoneId": "back",
            "pattern": pattern,
        }
    ]
    assert back.is_on
    assert not front.is_on


async def test_three_explicit_pixels_cover_the_entire_zone(coordinator, vendor):
    # Given the local API reports exactly three explicit blue pixel indices.
    vendor.states["hub"] = {
        "onState": True,
        "architectural": {
            "brightness": 80,
            "staticColors": [{"lights": [10, 11, 12], "color": 16711680}],
        },
    }
    # When the actual local response is decoded and mapped onto the configured zone.
    coordinator.data = await coordinator._async_update_data()
    front = GemstoneZoneLight(coordinator, "hub", "front")
    # Then pixel 10 is not mistaken for a range header, and the zone is lit blue at 80.
    assert front.is_on
    assert front.rgbw_color == (0, 0, 255, 0)
    assert front.brightness == 80


async def test_endpoints_alone_do_not_imply_uniform_zone_coverage(coordinator):
    # Given a static layout colors the endpoints but leaves the middle pixel unassigned.
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {"staticColors": [{"lights": [10, 12], "color": 255}]},
    }
    # When zone state is derived from the explicit pixels.
    front = GemstoneZoneLight(coordinator, "hub", "front")
    # Then it must not report the whole zone as a uniform red.
    assert front.rgbw_color is None


async def test_local_zones_keep_independent_brightness_after_echo(coordinator, vendor):
    # Given a local layout with red front at 80 and white back at 200.
    coordinator.data = await coordinator._async_update_data()
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {
            "zonePatterns": [
                {
                    "zoneId": "front",
                    "pattern": {
                        "colors": [255],
                        "brightness": 80,
                        "animation": "motionless",
                    },
                }
            ]
        },
    }
    # When the back is added and a later poll echoes the physical pixel colors.
    await coordinator.async_set_zone(
        "hub", "back", {"color": 4278190080, "brightness": 200, "animation": "Solid"}
    )
    await asyncio.sleep(5.05)  # Let the real command-settling window expire.
    coordinator.data = await coordinator._async_update_data()
    # Then physical channels encode independent brightness and logical zone colors remain full scale.
    sent = vendor.writes[-1][3]["architectural"]
    assert sent["brightness"] == 255
    assert sent["staticColors"] == [
        {"lights": [10, 11, 12], "color": 80},
        {"lights": [13, 14, 15], "color": 3355443200},
    ]
    assert GemstoneZoneLight(coordinator, "hub", "front").brightness == 80
    assert GemstoneZoneLight(coordinator, "hub", "back").rgbw_color == (0, 0, 0, 255)
    assert GemstoneZoneLight(coordinator, "hub", "back").brightness == 200


async def test_zone_edit_does_not_discard_unmapped_pixel_content(coordinator, vendor):
    # Given an external pixel layout includes content outside the configured zones.
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {"staticColors": [{"lights": [1, 2], "color": 255}]},
    }
    # When a zone edit would otherwise reconstruct and lose that unrelated content.
    with pytest.raises(HomeAssistantError, match="cannot be preserved"):
        await coordinator.async_set_zone("hub", "front", {"color": 65280})
    # Then no replacement command is sent to the controller.
    assert vendor.writes == []
