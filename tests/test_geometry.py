"""Pixel selections must survive decoding, control, persistence and import."""

from copy import deepcopy

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.gemstone_lights.coordinator import GemstoneCoordinator
from custom_components.gemstone_lights.geometry import decode_lights
from custom_components.gemstone_lights.light import GemstoneZoneLight


async def local_layout(coordinator, vendor, lights, back=None):
    """Supply imported native geometry, then poll the controller over LAN."""
    coordinator._zones["hub"][0]["lights"] = lights
    if back is not None:
        coordinator._zones["hub"][1]["lights"] = back
    vendor.states["hub"] = {"onState": False}
    coordinator.data = await coordinator._async_update_data()


@pytest.mark.parametrize(
    "lights,expected", [([2], [2]), ([2, 7], [2, 7]), ([2, 7, 12], [2, 7, 12])]
)
async def test_short_literal_zone_controls_only_its_selected_pixels(
    coordinator, vendor, lights, expected
):
    # Given a native zone with one, two or three explicit pixel indices.
    await local_layout(coordinator, vendor, lights)
    # When the zone is turned red through the actual light entity.
    await GemstoneZoneLight(coordinator, "hub", "front").async_turn_on(
        rgbw_color=(255, 0, 0, 0)
    )
    # Then the LAN command includes every selected pixel and no intervening pixels.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": expected, "color": 255}
    ]


async def test_mixed_ranges_repeat_palette_across_selected_pixels_without_filling_gaps(
    coordinator, vendor
):
    # Given two compressed runs plus a literal pixel, separated by unselected gaps.
    await local_layout(coordinator, vendor, [0, 0, 3, 5, 5, 8, 10])
    # When a red/green motionless palette is played in that zone.
    await coordinator.async_play_zone_pattern(
        "hub", "front", {"colors": [255, 65280], "animation": "motionless"}
    )
    # Then palette position advances across selected pixels, leaving indices 4 and 9 untouched.
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": [0, 2, 5, 7, 10], "color": 255},
        {"lights": [1, 3, 6, 8], "color": 65280},
    ]
    assert "front" not in coordinator.zone_ranges("hub")


async def test_gapped_zone_readback_and_turn_off_preserve_neighbor(coordinator, vendor):
    # Given complete red coverage of a two-pixel zone and a blue neighboring zone.
    await local_layout(coordinator, vendor, [2, 7], [3, 4, 5])
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {
            "brightness": 80,
            "staticColors": [
                {"lights": [2, 7], "color": 255},
                {"lights": [3, 4, 5], "color": 16711680},
            ],
        },
    }
    front = GemstoneZoneLight(coordinator, "hub", "front")
    observed = (front.is_on, front.rgbw_color, front.brightness)
    # When the front zone is turned off from explicit-pixel readback.
    await front.async_turn_off()
    # Then the front was reported correctly and only the original dimmed blue neighbor remains.
    assert observed == (True, (255, 0, 0, 0), 80)
    assert vendor.writes[-1][3]["architectural"]["staticColors"] == [
        {"lights": [3, 4, 5], "color": 5242880}
    ]


async def test_pixels_in_a_zone_gap_are_not_discarded_by_neighbor_reconstruction(
    coordinator, vendor
):
    # Given a separate lit pixel in the gap between a zone's two selected pixels.
    await local_layout(coordinator, vendor, [2, 7], [10, 11, 12])
    coordinator.data["devices"]["hub"]["state"] = {
        "onState": True,
        "architectural": {
            "staticColors": [
                {"lights": [2, 7], "color": 255},
                {"lights": [4], "color": 65280},
            ],
        },
    }
    # When turning off the zone would otherwise discard the unrelated green pixel.
    with pytest.raises(HomeAssistantError, match="cannot be preserved"):
        await GemstoneZoneLight(coordinator, "hub", "front").async_turn_off()
    # Then the edit is refused before either transport receives a destructive replacement.
    assert vendor.writes == []


@pytest.mark.parametrize("lights", [[2], [2, 7], [0, 0, 3, 7]])
async def test_unchanged_native_geometry_keeps_local_animated_control(
    coordinator, vendor, lights
):
    # Given a short or gapped zone already registered on verified firmware 1.1.5.
    await local_layout(coordinator, vendor, lights)
    # When an animation targets that original native zone.
    await coordinator.async_play_zone_pattern(
        "hub",
        "front",
        {"id": "test", "name": "Chase", "colors": [255], "animation": "chase"},
    )
    # Then the native zone ID and animation reach the controller over LAN.
    assert vendor.writes[-1][0] == "local"
    assert vendor.writes[-1][3]["architectural"]["zonePatterns"][0]["zoneId"] == "front"
    assert (
        vendor.writes[-1][3]["architectural"]["zonePatterns"][0]["pattern"]["animation"]
        == "chase"
    )


async def test_matching_tail_does_not_hide_a_resized_native_zone(coordinator, vendor):
    # Given an HA override retaining only the final three pixels of an existing native zone.
    await local_layout(coordinator, vendor, [0, 1, 4, 5, 6], [10, 11, 12])
    await coordinator.catalog.save("hub", "zone", "Front", {"start": 4, "end": 6})
    # When an animated action would still address the firmware's original larger zone.
    with pytest.raises(HomeAssistantError, match="motionless palettes only"):
        await coordinator.async_play_zone_pattern(
            "hub", "front", {"colors": [255], "animation": "chase"}
        )
    # Then complete geometry comparison blocks playback.
    assert vendor.writes == []


@pytest.mark.parametrize(
    "lights", [[], [True], [-1], [65536], [2.5], ["2"], [2, 2], [7, 7, 2], [2, 2, 5, 4]]
)
async def test_invalid_geometry_never_becomes_a_guessed_control_range(
    coordinator, vendor, lights
):
    # Given unusable, truncated, overlapping or out-of-bounds geometry from the controller.
    await local_layout(coordinator, vendor, lights)
    # When a lighting command targets the affected zone.
    with pytest.raises(HomeAssistantError, match="complete pixel layout"):
        await coordinator.async_play_zone_pattern(
            "hub", "front", {"colors": [255], "animation": "motionless"}
        )
    # Then no guessed interval is sent.
    assert vendor.writes == []


async def test_legacy_local_catalog_migrates_without_lighting_its_count_header(
    coordinator,
):
    # Given a pre-fix local catalog whose ranges begin with a pixel count.
    coordinator.catalog.restore(
        {
            "zones": {
                "hub": [
                    {"id": "ha:porch", "name": "Porch", "lights": [3, 20, 22]},
                    {"id": "ha:single", "name": "Single", "lights": [1, 30, 30]},
                ]
            }
        }
    )
    # When restored selections are exported and restored again in the current format.
    exported = coordinator.catalog.export("hub")
    coordinator.catalog.restore(deepcopy(coordinator.catalog.data))
    # Then counts are never interpreted as physical indices, IDs survive, and migration is idempotent.
    assert coordinator.zone_pixels("hub")["ha:porch"] == (20, 21, 22)
    assert coordinator.zone_pixels("hub")["ha:single"] == (30,)
    assert exported["version"] == 2
    assert next(z for z in exported["zones"] if z["id"] == "ha:porch")["lights"] == [
        20,
        21,
        22,
    ]


async def test_export_import_preserves_gaps_and_design_references(
    hass, entry, coordinator
):
    # Given a native zone with two separated literal selections referenced by a saved design.
    coordinator._zones["hub"][0]["lights"] = [0, 1, 2, 4, 5, 6]
    await coordinator.catalog.save(
        "hub",
        "design",
        "Keep gaps",
        {"zonePatterns": [{"zoneId": "front", "pattern": {"colors": [255]}}]},
    )
    exported = coordinator.catalog.export("hub")
    fresh = GemstoneCoordinator(hass, entry)
    try:
        # When a new offline coordinator imports the portable catalog.
        await fresh.catalog.import_data("hub", exported)
        # Then both runs survive under the original zone ID, and the design still targets it.
        assert fresh.zone_pixels("hub")["front"] == (0, 1, 2, 4, 5, 6)
        assert fresh.designs("hub")[0]["zonePatterns"][0]["zoneId"] == "front"
    finally:
        await fresh.async_shutdown()


async def test_overlap_checks_use_actual_pixels_including_short_selections(coordinator):
    # Given a gapped zone whose bounding interval contains free pixels.
    coordinator._zones["hub"][0]["lights"] = [2, 7]
    # When a zone is saved in its gap, followed by an overlapping edit.
    await coordinator.catalog.save("hub", "zone", "Gap", {"start": 3, "end": 5})
    before = deepcopy(coordinator.catalog.data)
    with pytest.raises(HomeAssistantError, match="overlaps Front"):
        await coordinator.catalog.save(
            "hub", "zone", "Conflict", {"start": 7, "end": 8}
        )
    # Then the free gap is usable, but the short zone's actual pixel remains protected.
    assert coordinator.zone_pixels("hub")[
        coordinator.catalog.entries("zone", "hub")[0]["id"]
    ] == (3, 4, 5)
    assert coordinator.catalog.data == before


async def test_ambiguous_legacy_import_does_not_partially_change_catalog(coordinator):
    # Given an old export mixing a safe entry with an unmarked count-or-literal triple.
    before = deepcopy(coordinator.catalog.data)
    # When importing it would require guessing whether pixel 3 belongs to the second zone.
    with pytest.raises(HomeAssistantError, match="Ambiguous version 1 zone"):
        await coordinator.catalog.import_data(
            "hub",
            {
                "version": 1,
                "zones": [
                    {"id": "ha:old", "name": "Old", "lights": [1, 30, 30]},
                    {"id": "external", "name": "Ambiguous", "lights": [3, 10, 12]},
                ],
            },
        )
    # Then neither entry is committed and the user gets a re-export instruction.
    assert coordinator.catalog.data == before


def test_compressed_geometry_expansion_stays_within_physical_index_bounds():
    # Given a run covering the full representable index space and a malformed larger endpoint.
    valid, oversized = [0, 0, 65535], [0, 0, 65536]
    # When both are decoded.
    pixels = decode_lights(valid)
    with pytest.raises(ValueError):
        decode_lights(oversized)
    # Then the valid run expands exactly once to each physical index, without clipping the oversized input.
    assert pixels == tuple(range(65536))


async def test_identified_legacy_local_export_keeps_its_original_range(coordinator):
    # Given an old exported HA-owned zone with the count/start/end encoding.
    catalog = {
        "version": 1,
        "zones": [{"id": "ha:old", "name": "Old", "lights": [2, 20, 21]}],
    }
    # When the previous-format export is imported and exported again.
    await coordinator.catalog.import_data("hub", catalog)
    exported = coordinator.catalog.export("hub")
    # Then the count is removed, the two selected indices survive, and the zone ID remains stable.
    assert next(z for z in exported["zones"] if z["id"] == "ha:old")["lights"] == [
        20,
        21,
    ]
    assert exported["version"] == 2


async def test_invalid_explicit_import_is_atomic(coordinator):
    # Given a version 2 catalog with a valid first zone and duplicate indices in its second zone.
    before = deepcopy(coordinator.catalog.data)
    # When import validates the explicit selections.
    with pytest.raises(HomeAssistantError, match="Invalid zone pixel selection"):
        await coordinator.catalog.import_data(
            "hub",
            {
                "version": 2,
                "zones": [
                    {"id": "good", "name": "Good", "lights": [20, 22]},
                    {"id": "bad", "name": "Bad", "lights": [30, 30]},
                ],
            },
        )
    # Then even the valid first zone is rolled back.
    assert coordinator.catalog.data == before


async def test_invalid_zone_export_reports_the_layout_problem(coordinator):
    # Given a malformed compressed range in the controller's zone inventory.
    coordinator._zones["hub"][0]["lights"] = [2, 2]
    before = deepcopy(coordinator.catalog.data)
    # When a portable backup is requested.
    with pytest.raises(
        HomeAssistantError, match="Cannot export an invalid zone pixel layout"
    ):
        coordinator.catalog.export("hub")
    # Then export reports the unusable layout without changing the saved catalog.
    assert coordinator.catalog.data == before
