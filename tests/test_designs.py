"""Design transport must match actual controller capabilities."""


async def test_existing_animated_zone_uses_verified_local_firmware(coordinator, vendor):
    # Given a reachable Hub2 1.1.5 and an existing animated zone with its own level.
    coordinator.data = await coordinator._async_update_data()
    design = {
        "id": "saved",
        "brightness": 128,
        "zonePatterns": [
            {
                "zoneId": "front",
                "pattern": {
                    "animation": "chase",
                    "colors": [255, 65280],
                    "brightness": 64,
                },
            }
        ],
    }
    # When the saved design is selected.
    await coordinator.async_play_design("hub", design)
    # Then native LAN playback keeps both brightness levels and the complete animation palette.
    assert len(vendor.writes) == 1
    assert vendor.writes[0][0] == "local"
    assert vendor.writes[0][3]["architectural"] == {**design, "preview": False}


async def test_static_pixel_design_uses_local_transport(coordinator, vendor):
    # Given a reachable local controller and a supported explicit-pixel design.
    coordinator.data = await coordinator._async_update_data()
    design = {
        "staticColors": [{"lights": [10, 11, 12], "color": 255}],
        "brightness": 80,
    }
    # When the pixel design is played.
    await coordinator.async_play_design("hub", design)
    # Then it is sent over LAN with its brightness and pixel assignments intact.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"] == {**design, "preview": False}


async def test_new_animated_zone_is_rejected_before_any_transport(coordinator, vendor):
    # Given a new HA-only zone that has no corresponding firmware zone definition.
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    await coordinator.catalog.save("hub", "zone", "Porch", {"start": 20, "end": 22})
    zone_id = next(z["id"] for z in coordinator.zones("hub") if z["name"] == "Porch")
    # When an animated design tries to use that new zone.
    with pytest.raises(HomeAssistantError, match="motionless palettes only"):
        await coordinator.async_play_design(
            "hub",
            {
                "zonePatterns": [
                    {
                        "zoneId": zone_id,
                        "pattern": {"colors": [255], "animation": "chase"},
                    }
                ]
            },
        )
    # Then the controller never receives a design that cannot render the requested range.
    assert vendor.writes == []


async def test_local_static_zone_repeats_palette_and_scales_each_channel(
    coordinator, vendor
):
    # Given a three-pixel zone and a two-color static palette at half master brightness.
    coordinator.data = await coordinator._async_update_data()
    # When the palette is played in the front zone.
    await coordinator.async_play_design(
        "hub",
        {
            "brightness": 128,
            "zonePatterns": [
                {
                    "zoneId": "front",
                    "pattern": {"colors": [255, 4278190080], "animation": "motionless"},
                }
            ],
        },
    )
    # Then colors repeat from the zone start and RGB and white dim consistently on the wire.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": [10, 12], "color": 128},
        {"lights": [11], "color": 2147483648},
    ]
