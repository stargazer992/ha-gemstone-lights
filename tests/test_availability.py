"""Availability follows observed device reachability, without false off events."""

from custom_components.gemstone_lights.light import GemstoneLight


async def test_failed_state_read_preserves_state_but_marks_unavailable(
    coordinator, vendor
):
    # Given the last successful state is on and the next state endpoint fails.
    vendor.failures["/device-state/currently-playing"] = 503
    light = GemstoneLight(coordinator, "hub")
    # When a normal coordinator poll runs.
    coordinator.data = await coordinator._async_update_data()
    # Then the device is unavailable and its last on state is not replaced by a false off.
    assert not light.available
    assert light.is_on


async def test_local_read_overrides_stale_imported_offline_flag(coordinator, vendor):
    # Given the imported record says offline but the LAN controller answers normally.
    coordinator._known_devices[0]["online"] = False
    light = GemstoneLight(coordinator, "hub")
    # When the coordinator reads the controller locally.
    coordinator.data = await coordinator._async_update_data()
    # Then the light stays controllable and accurately reports on.
    assert light.available
    assert light.is_on
    assert coordinator.is_local("hub")
