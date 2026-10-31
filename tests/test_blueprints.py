"""Execute shipped blueprints with HA's script and automation engines."""

from pathlib import Path

import pytest
from homeassistant.components.blueprint import BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict


def configured_blueprint(path, inputs):
    blueprint = Blueprint(
        load_yaml_dict(Path("blueprints") / path), schema=BLUEPRINT_SCHEMA
    )
    instance = BlueprintInputs(blueprint, {"use_blueprint": {"input": inputs}})
    instance.validate()
    return instance.async_substitute()


async def test_playlist_advances_palettes_and_stops_after_one_pass(
    hass, loaded_entry, vendor
):
    # Given the shipped playlist blueprint with two different patterns and one pass.
    light = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )
    config = configured_blueprint(
        "script/gemstone_lights/local_playlist.yaml",
        {
            "controller": light,
            "loops": 1,
            "steps": [
                {
                    "kind": "pattern",
                    "content": {"colors": [255, 0], "animation": "chase"},
                    "seconds": 2,
                },
                {
                    "kind": "pattern",
                    "content": {"colors": [65280, 0], "animation": "chase"},
                    "seconds": 2,
                },
            ],
        },
    )
    await async_setup_component(hass, "script", {"script": {"local_playlist": config}})
    # When HA runs the playlist to completion.
    await hass.services.async_call("script", "local_playlist", {}, blocking=True)
    # Then both palettes reach the LAN controller in order and the script stops advancing.
    assert [write[3]["pattern"]["colors"] for write in vendor.writes] == [
        [255, 0],
        [65280, 0],
    ]
    assert all(write[0] == "local" for write in vendor.writes)
    assert hass.states.get("script.local_playlist").state == "off"


@pytest.mark.parametrize(
    ("blueprint", "source", "off", "on", "extra"),
    [
        (
            "local_schedule",
            "schedule.lights",
            "off",
            "on",
            {"schedule": "schedule.lights"},
        ),
        ("local_sun", "sun.sun", "above_horizon", "below_horizon", {}),
    ],
)
async def test_schedule_applies_content_then_turns_off(
    hass, loaded_entry, vendor, blueprint, source, off, on, extra
):
    # Given a shipped schedule blueprint whose local input is initially inactive.
    light = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )
    hass.states.async_set(source, off)
    config = configured_blueprint(
        f"automation/gemstone_lights/{blueprint}.yaml",
        {
            "controller": light,
            "kind": "pattern",
            "content": {"colors": [4278190080]},
            **extra,
        },
    )
    config["id"] = blueprint
    await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    # When the schedule becomes active and subsequently ends.
    hass.states.async_set(source, on)
    await hass.async_block_till_done()
    lit = vendor.states["hub"].copy()
    hass.states.async_set(source, off)
    await hass.async_block_till_done()
    # Then HA plays the white palette locally and switches power off at the end.
    assert lit["pattern"]["colors"] == [4278190080]
    assert vendor.states["hub"]["onState"] is False
    assert [write[0] for write in vendor.writes] == ["local", "local"]


async def test_holiday_calendar_plays_event_names_and_turns_off(
    hass, loaded_entry, vendor
):
    # Given saved patterns named after calendar events, and the holiday blueprint.
    loaded_entry._patterns = [
        {"folder": "", "name": "Glamo WW", "data": {"id": "ww", "colors": [255]}},
        {"folder": "", "name": "Christmas", "data": {"id": "xmas", "colors": [65280]}},
    ]
    light = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )
    hass.states.async_set("calendar.lights", "off", {"message": ""})
    config = configured_blueprint(
        "automation/gemstone_lights/holiday_calendar.yaml",
        {"calendar": "calendar.lights", "controllers": [light]},
    )
    config["id"] = "holiday_calendar"
    await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()
    # When one event starts, a back-to-back event follows, and then it ends.
    hass.states.async_set("calendar.lights", "on", {"message": "Glamo WW"})
    await hass.async_block_till_done()
    first = vendor.states["hub"]["pattern"]["id"]
    hass.states.async_set("calendar.lights", "on", {"message": " Christmas "})
    await hass.async_block_till_done()
    second = vendor.states["hub"]["pattern"]["id"]
    hass.states.async_set("calendar.lights", "off", {"message": ""})
    await hass.async_block_till_done()
    # Then each event's pattern plays locally and the lights go off at the end.
    assert (first, second) == ("ww", "xmas")
    assert vendor.states["hub"]["onState"] is False
    assert {write[0] for write in vendor.writes} == {"local"}
