"""Commands must publish successful state even while the controller echo lags."""

from custom_components.gemstone_lights.light import GemstoneLight


async def test_successful_color_is_immediate_and_survives_stale_poll(
    coordinator, vendor
):
    # Given the controller accepts writes but reports its previous state for a while.
    vendor.echo_writes = False
    light = GemstoneLight(coordinator, "hub")
    # When a dim white-channel color is sent, followed by a stale poll.
    await coordinator.async_play_color("hub", 4278190080, 80)
    coordinator.data = await coordinator._async_update_data()
    # Then the controller receives brightness separately and HA retains the
    # requested colour, shown as the app's Warm White swatch.
    assert vendor.writes[-1][3]["colorB"] == {"value": 4278190080, "brightness": 80}
    assert light.rgbw_color == (253, 244, 188, 0)
    assert light.brightness == 80
