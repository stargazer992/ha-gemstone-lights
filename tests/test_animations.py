"""Effects, palette and busy handling as the controller sees them."""

import json

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.gemstone_lights.animations import ANIMATION_SPECS
from custom_components.gemstone_lights.const import ANIMATIONS
from custom_components.gemstone_lights.local_api import (
    GemstoneLocalApi,
    GemstoneLocalError,
)
from custom_components.gemstone_lights.palette import FAVORITE_COLORS


def _light_id(hass):
    return er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )


async def _turn_on(hass, **data):
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": _light_id(hass), **data}, blocking=True
    )


def test_every_effect_has_a_spec():
    # Given the effects offered in Home Assistant, then each has a pattern spec.
    assert set(ANIMATIONS) == set(ANIMATION_SPECS)


async def test_effect_without_direction_gets_its_extra_parameters(
    hass, loaded_entry, vendor
):
    # Given a loaded controller.
    # When Fireworks is picked as an effect.
    await _turn_on(hass, effect="fireworks")

    # Then the pattern has no direction, a background colour and every extra.
    pattern = vendor.writes[-1][3]["pattern"]
    assert "direction" not in pattern
    assert pattern["backgroundColor"] == 0
    assert pattern["extraParameters"] == {
        "version": 0,
        "0": {"value": 4, "name": "Firework Count"},
        "1": {"value": 4278190080, "name": "Rocket Color"},
        "2": {"value": 25, "name": "Rocket Travel %"},
    }


async def test_effect_with_direction_drops_background_and_extras(
    hass, loaded_entry, vendor
):
    # Given a loaded controller.
    # When Chase is picked as an effect.
    await _turn_on(hass, effect="chase")

    # Then only the fields Chase reads are sent.
    pattern = vendor.writes[-1][3]["pattern"]
    assert pattern["direction"] == 0
    assert "backgroundColor" not in pattern
    assert "extraParameters" not in pattern


async def test_picker_is_seeded_with_app_swatches(hass, loaded_entry):
    # Given a newly added light, then its favourites are the app's swatches.
    options = er.async_get(hass).async_get(_light_id(hass)).options["light"]
    assert options["favorite_colors"] == FAVORITE_COLORS


async def test_swatch_sends_the_app_value(hass, loaded_entry, vendor):
    # Given a loaded controller.
    # When the Yellow swatch is picked.
    await _turn_on(hass, rgbw_color=(255, 255, 0, 0), effect="Solid")

    # Then the controller gets the app's LED yellow and HA shows the swatch.
    assert vendor.writes[-1][3]["colorB"]["value"] == 255 | 87 << 8
    await hass.async_block_till_done()
    assert hass.states.get(_light_id(hass)).attributes["rgbw_color"] == (255, 255, 0, 0)


async def test_busy_controller_is_retried_once(hass, http):
    # Given a controller that answers busy once.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    url = "http://192.0.2.10/device-control/play"
    http.post(url, status=503)
    http.post(url, status=200)

    # When a command is sent, then it is resent and succeeds.
    await client.async_set_power(True)
    sent = next(iter(http.requests.values()))
    assert len(sent) == 2
    assert json.loads(sent[1].kwargs["data"])["state"]["desired"][
        "currentlyPlaying"
    ] == {"onState": True}


async def test_busy_poll_is_retried_once_then_fails(hass, http):
    # Given a controller that stays busy.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    url = "http://192.0.2.10/device-state/hub-settings"
    http.get(url, status=503)
    http.get(url, status=503)

    # When settings are read, then two attempts are made and the error surfaces.
    try:
        await client.async_get_settings()
    except GemstoneLocalError as err:
        assert "503" in str(err)
    else:
        raise AssertionError("expected GemstoneLocalError")
    assert len(next(iter(http.requests.values()))) == 2
