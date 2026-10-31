"""The fake controller in tools/ speaks the same API the integration uses."""

import sys
from pathlib import Path

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.gemstone_lights.local_api import (
    GemstoneLocalApi,
    GemstoneLocalError,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import gemstone_sim  # noqa: E402


@pytest.fixture
async def sim(aiohttp_server, socket_enabled):
    controller = gemstone_sim.FakeController("Sim", "127.0.0.1")
    server = await aiohttp_server(gemstone_sim.build_app(controller))
    controller.port = server.port
    return controller


def _client(hass, sim):
    return GemstoneLocalApi(async_get_clientsession(hass), f"127.0.0.1:{sim.port}")


async def test_client_reads_and_commands_the_fake(hass, sim):
    # Given a running fake controller.
    client = _client(hass, sim)

    # When the integration's client reads it and turns it off.
    settings = await client.async_get_settings()
    await client.async_set_power(False)
    state = await client.async_get_state()

    # Then settings parse and power changed while the colour was kept.
    assert settings["pixelCount"][0] == 150
    assert state["onState"] is False
    assert state["colorB"]["value"] == 12614435


async def test_client_rides_out_one_busy_reply(hass, sim):
    # Given a fake that answers busy once.
    sim.fault = "busy-once"

    # When a colour is sent, then the retry lands it.
    await _client(hass, sim).async_play(
        {"onState": True, "colorB": {"value": 255, "brightness": 255}}
    )
    assert sim.playing["colorB"]["value"] == 255
    assert [entry["status"] for entry in sim.log] == [200, 503]


async def test_fake_rejects_out_of_range_commands(hass, sim):
    # Given a fake controller.
    # When a pattern with speed 0 is sent, then it is refused with 400.
    with pytest.raises(GemstoneLocalError, match="400"):
        await _client(hass, sim).async_play(
            {
                "onState": True,
                "pattern": {
                    "name": "x",
                    "animation": "chase",
                    "colors": [255],
                    "speed": 0,
                },
            }
        )


async def test_external_change_shows_up_on_poll(hass, sim):
    # Given a fake controller whose colour is changed "from the app".
    color = sim.external_change()

    # When it is polled, then the new colour is reported.
    assert (await _client(hass, sim).async_get_state())["colorB"]["value"] == color


async def test_down_controller_is_unreachable(hass, sim):
    # Given a fake that drops every request.
    sim.fault = "down"

    # When it is polled, then the client reports a connection failure.
    with pytest.raises(GemstoneLocalError):
        await _client(hass, sim).async_get_state()
