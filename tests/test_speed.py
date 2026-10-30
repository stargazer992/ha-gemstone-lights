"""Effect speed must not power an off controller back on."""

import pytest

from custom_components.gemstone_lights.number import GemstoneSpeed


@pytest.mark.parametrize("on", [False, True])
async def test_speed_only_replays_active_patterns(coordinator, vendor, on):
    # Given a retained multi-color pattern on a controller in the specified power state.
    pattern = {
        "colors": [255, 65280],
        "animation": "chase",
        "speed": 17,
        "direction": 1,
    }
    coordinator.data["devices"]["hub"]["state"] = {"onState": on, "pattern": pattern}
    speed = GemstoneSpeed(coordinator, "hub")
    # When speed is changed through the number entity.
    await speed.async_set_native_value(100)
    # Then an active pattern changes speed only; an off controller receives no command.
    assert speed.native_value == 100
    assert [write[3]["pattern"] for write in vendor.writes] == (
        [{**pattern, "speed": 100}] if on else []
    )
