"""Play saved or library content by name, across several controllers at once."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

WARM = {"id": "warm", "name": "Glamo WW", "colors": [255], "animation": "fade"}
XMAS = {"id": "xmas", "name": "Glamo WW", "colors": [65280], "animation": "chase"}


def light_id(hass, unique_id):
    return er.async_get(hass).async_get_entity_id("light", "gemstone_lights", unique_id)


async def play(hass, entity_id, **data):
    await hass.services.async_call(
        "gemstone_lights",
        "play_by_name",
        {"entity_id": entity_id, **data},
        blocking=True,
    )


async def test_saved_pattern_plays_by_name(hass, loaded_entry, vendor):
    # Given a saved pattern imported from the account.
    loaded_entry._patterns = [{"folder": "Warm", "name": "Glamo WW", "data": WARM}]
    # When it is played by name.
    await play(hass, light_id(hass, "hub_light"), name="Glamo WW")
    # Then exactly that pattern reaches the controller.
    assert vendor.writes[-1][3]["pattern"]["id"] == "warm"


async def test_duplicate_names_need_the_dropdown_label(hass, loaded_entry, vendor):
    # Given two saved patterns with the same name in different folders.
    loaded_entry._patterns = [
        {"folder": "Warm", "name": "Glamo WW", "data": WARM},
        {"folder": "Holiday", "name": "Glamo WW", "data": XMAS},
    ]
    light = light_id(hass, "hub_light")
    # When the bare name is used, the error lists the choices.
    with pytest.raises(HomeAssistantError, match=r"Glamo WW \(Holiday\)"):
        await play(hass, light, name="Glamo WW")
    # Then the dropdown label or a folder selects exactly one.
    await play(hass, light, name="Glamo WW (Holiday)")
    assert vendor.writes[-1][3]["pattern"]["id"] == "xmas"
    await play(hass, light, name="Glamo WW", folder="Warm")
    assert vendor.writes[-1][3]["pattern"]["id"] == "warm"


async def test_saved_design_plays_on_the_controller(hass, loaded_entry, vendor):
    # Given a saved design.
    loaded_entry._designs["hub"] = [
        {"id": "d1", "name": "Porch", "zonePatterns": [], "animation": "motionless"}
    ]
    # When it is played by name.
    await play(hass, light_id(hass, "hub_light"), name="Porch")
    # Then the controller receives that design.
    assert vendor.writes[-1][3]["architectural"]["name"] == "Porch"


async def test_falls_back_to_library_and_suggests_names(hass, loaded_entry, vendor):
    # Given a library pattern and no saved item with its name.
    loaded_entry.library.folders = {
        "holidays / Christmas": [
            {"name": "Holiday", "data": {"colors": [255, 65280], "animation": "chase"}}
        ]
    }
    light = light_id(hass, "hub_light")
    # When it is played by name.
    await play(hass, light, name="Holiday")
    # Then the library pattern plays; an unknown name suggests close matches.
    assert vendor.writes[-1][3]["pattern"]["colors"] == [255, 65280]
    with pytest.raises(HomeAssistantError, match="Holiday"):
        await play(hass, light, name="Holidya")


async def test_one_action_plays_on_every_targeted_controller(
    hass, loaded_entry, vendor, hass_storage
):
    # Given a second controller in its own entry.
    garage = {"id": "garage", "name": "Garage", "hub": {"localIp": "192.0.2.11"}}
    vendor.devices.append(garage)
    vendor.states["garage"] = {"onState": True, "color": 255}
    second = MockConfigEntry(
        domain="gemstone_lights",
        version=2,
        data={"local_only": True, "host": "192.0.2.11", "local_device": garage},
        unique_id="garage",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    for coordinator in (loaded_entry, second.runtime_data):
        coordinator._patterns = [{"folder": "Warm", "name": "Glamo WW", "data": WARM}]
    # When one action targets both controller lights.
    await play(
        hass,
        [light_id(hass, "hub_light"), light_id(hass, "garage_light")],
        name="Glamo WW",
    )
    # Then both controllers receive the pattern.
    assert {(w[1], w[3]["pattern"]["id"]) for w in vendor.writes} == {
        ("hub", "warm"),
        ("garage", "warm"),
    }
    await hass.config_entries.async_unload(second.entry_id)
