"""Availability follows observed device reachability, without false off events."""

from custom_components.gemstone_lights.const import LOCAL_MISSED_POLLS
from custom_components.gemstone_lights.light import GemstoneLight


async def test_repeated_failed_reads_preserve_state_but_mark_unavailable(
    coordinator, vendor
):
    # Given the last successful state is on and the state endpoint keeps failing.
    vendor.failures["/device-state/currently-playing"] = 503
    light = GemstoneLight(coordinator, "hub")
    # When three consecutive coordinator polls fail.
    for _ in range(LOCAL_MISSED_POLLS):
        coordinator.data = await coordinator._async_update_data()
    # Then the device is unavailable and its last on state is not replaced by a false off.
    assert not light.available
    assert light.is_on


async def test_occasional_missed_reads_keep_controller_available(coordinator, vendor):
    # Given a controller that misses two polls in a row.
    vendor.failures["/device-state/currently-playing"] = 503
    light = GemstoneLight(coordinator, "hub")
    for _ in range(LOCAL_MISSED_POLLS - 1):
        coordinator.data = await coordinator._async_update_data()
    # Then it stays available with its last known state.
    assert light.available
    assert light.is_on
    # When it answers again, the miss count resets.
    vendor.failures.clear()
    coordinator.data = await coordinator._async_update_data()
    vendor.failures["/device-state/currently-playing"] = 503
    for _ in range(LOCAL_MISSED_POLLS - 1):
        coordinator.data = await coordinator._async_update_data()
    assert light.available


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
