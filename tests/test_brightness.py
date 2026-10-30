"""Brightness must operate on logical RGBW, not already-dimmed channels."""

import asyncio

from custom_components.gemstone_lights.light import GemstoneLight, GemstoneZoneLight


async def test_dim_then_brighten_restores_original_color(coordinator, vendor):
    # Given a full red controller.
    light = GemstoneLight(coordinator, "hub")
    # When it is dimmed, its physical echo is polled, and then brightness is restored.
    await light.async_turn_on(brightness=80)
    await asyncio.sleep(5.05)  # Let the real command-settling window expire.
    coordinator.data = await coordinator._async_update_data()
    await light.async_turn_on(brightness=255)
    # Then red is kept at full scale and only the separate brightness changes.
    assert [write[3]["colorB"] for write in vendor.writes] == [
        {"value": 255, "brightness": 80},
        {"value": 255, "brightness": 255},
    ]
    assert light.rgbw_color == (255, 0, 0, 0)
    assert light.brightness == 255


async def test_dimming_whole_solid_design_preserves_zone_ratios_offline(
    coordinator, vendor
):
    # Given a local design with front at 80 and back at 200.
    coordinator.data = await coordinator._async_update_data()
    await coordinator.async_play_design(
        "hub",
        {
            "brightness": 255,
            "zonePatterns": [
                {
                    "zoneId": "front",
                    "pattern": {
                        "colors": [255],
                        "animation": "motionless",
                        "brightness": 80,
                    },
                },
                {
                    "zoneId": "back",
                    "pattern": {
                        "colors": [4278190080],
                        "animation": "motionless",
                        "brightness": 200,
                    },
                },
            ],
        },
    )
    # When the whole-controller light is dimmed to approximately half brightness.
    await GemstoneLight(coordinator, "hub").async_turn_on(brightness=128)
    # Then the operation stays local and retains the zones' relative brightness.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": [10, 11, 12], "color": 40},
        {"lights": [13, 14, 15], "color": 1677721600},
    ]
    assert GemstoneZoneLight(coordinator, "hub", "front").brightness == 40
    assert GemstoneZoneLight(coordinator, "hub", "back").brightness == 100


async def test_external_color_change_replaces_remembered_brightness(
    coordinator, vendor
):
    # Given HA previously dimmed a red light.
    await coordinator.async_play_color("hub", 255, 80)
    await asyncio.sleep(5.05)  # Let the real command-settling window expire.
    vendor.states["hub"] = {"onState": True, "color": 65280}
    # When a later poll observes a different green color set outside HA.
    coordinator.data = await coordinator._async_update_data()
    light = GemstoneLight(coordinator, "hub")
    # Then the old red/brightness interpretation is discarded instead of masking the external change.
    assert light.rgbw_color == (0, 255, 0, 0)
    assert light.brightness == 255


async def test_power_change_retains_local_zone_brightness_interpretation(
    coordinator, vendor
):
    # Given a local solid zone whose physical color encodes its brightness.
    coordinator.data = await coordinator._async_update_data()
    await coordinator.async_play_design(
        "hub",
        {
            "brightness": 255,
            "zonePatterns": [
                {
                    "zoneId": "front",
                    "pattern": {
                        "colors": [255],
                        "animation": "motionless",
                        "brightness": 80,
                    },
                }
            ],
        },
    )
    # When power is switched off and the controller's retained pixel layout is read back.
    await coordinator.async_set_power("hub", False)
    await asyncio.sleep(5.05)  # Let the real command-settling window expire.
    coordinator.data = await coordinator._async_update_data()
    front = GemstoneZoneLight(coordinator, "hub", "front")
    # Then the zone is off while its logical red and brightness remain available for restoration.
    assert not front.is_on
    assert front.rgbw_color == (255, 0, 0, 0)
    assert front.brightness == 80
