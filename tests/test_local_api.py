"""Behavior of the actual local HTTP client at its network boundary."""

import json

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.gemstone_lights.local_api import (
    GemstoneLocalApi,
    GemstoneLocalError,
)


async def test_power_off_preserves_playing_content(hass, http):
    # Given a controller accepting the documented power command.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    http.post("http://192.0.2.10/device-control/play", status=200)

    # When power is switched off.
    await client.async_set_power(False)

    # Then no mode-reset fields are sent, so the current content survives.
    request = next(iter(http.requests.values()))[0]
    desired = json.loads(request.kwargs["data"])["state"]["desired"]
    assert desired == {"currentlyPlaying": {"onState": False}, "origin": "control4"}


async def test_color_replaces_other_modes(hass, http):
    # Given a controller that may already be showing another mode.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    http.post("http://192.0.2.10/device-control/play", status=200)

    # When a white-channel color is played at reduced brightness.
    await client.async_play(
        {"onState": True, "colorB": {"value": 4278190080, "brightness": 80}}
    )

    # Then the RGBW payload survives and every competing mode is cleared.
    request = next(iter(http.requests.values()))[0]
    playing = json.loads(request.kwargs["data"])["state"]["desired"]["currentlyPlaying"]
    assert playing == {
        "onState": True,
        "colorB": {"value": 4278190080, "brightness": 80},
        "pattern": None,
        "architectural": None,
        "impulse": None,
        "playlist": None,
    }


async def test_timed_out_command_is_sent_once_more(hass, http):
    # Given a controller that stalls on the first command and answers the next.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    url = "http://192.0.2.10/device-control/play"
    http.post(url, exception=TimeoutError())
    http.post(url, status=200)

    # When power is switched off.
    await client.async_set_power(False)

    # Then the command was resent and succeeded.
    assert len(next(iter(http.requests.values()))) == 2


async def test_command_fails_after_two_timeouts(hass, http):
    # Given a controller that does not answer at all.
    client = GemstoneLocalApi(async_get_clientsession(hass), "192.0.2.10")
    url = "http://192.0.2.10/device-control/play"
    http.post(url, exception=TimeoutError())
    http.post(url, exception=TimeoutError())

    # When power is switched off, then the timeout is reported.
    with pytest.raises(GemstoneLocalError, match="Timeout sending command"):
        await client.async_set_power(False)
    assert len(next(iter(http.requests.values()))) == 2
