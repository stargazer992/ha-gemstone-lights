"""Polling, commands, selection and storage without any cloud fallback."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import yaml
from homeassistant.helpers import entity_registry as er

from custom_components.gemstone_lights.const import LOCAL_MISSED_POLLS
from custom_components.gemstone_lights.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.gemstone_lights.select import (
    GemstoneDesignSelect,
    GemstoneLibraryPatternSelect,
    GemstonePatternSelect,
)

COMPONENT = Path(__file__).parent.parent / "custom_components" / "gemstone_lights"


async def test_slow_poll_does_not_delay_a_command(coordinator, vendor):
    # Given a state read that hangs on the controller.
    vendor.hold_reads = asyncio.Event()
    poll = asyncio.create_task(coordinator.async_refresh())
    while not vendor.reads_waiting:
        await asyncio.sleep(0.01)
    # When a command is sent while that read is outstanding.
    await asyncio.wait_for(coordinator.async_play_color("hub", 65280, 200), 3)
    vendor.hold_reads.set()
    await poll
    # Then the command went out immediately and the stale read did not replace it.
    assert vendor.writes[-1][3]["colorB"] == {"value": 65280, "brightness": 200}
    assert coordinator.device_state("hub")["colorB"]["value"] == 65280


async def test_controllers_are_polled_in_parallel(coordinator, vendor):
    # Given two controllers whose reads both stall.
    garage = {"id": "garage", "hub": {"localIp": "192.0.2.11"}}
    vendor.devices.append(garage)
    vendor.states["garage"] = {"onState": False}
    coordinator._known_devices.append(garage)
    vendor.hold_reads = asyncio.Event()
    # When a poll starts.
    poll = asyncio.create_task(coordinator.async_refresh())
    # Then both reads are in flight at once instead of one after the other.
    await asyncio.wait_for(_until(lambda: vendor.reads_waiting == 2), 3)
    vendor.hold_reads.set()
    await poll


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.01)


async def test_command_right_after_failed_poll_still_reaches_controller(
    coordinator, vendor
):
    # Given a poll that failed, marking the controller unavailable.
    vendor.failures["/device-state/currently-playing"] = 503
    for _ in range(LOCAL_MISSED_POLLS):
        await coordinator.async_refresh()
    assert not coordinator.device_available("hub")
    vendor.failures.clear()
    # When a command is sent before the next poll.
    await coordinator.async_set_power("hub", False)
    # Then it is sent over LAN and the controller is available again.
    assert vendor.writes[-1][0] == "local"
    assert coordinator.device_available("hub")


async def test_duplicate_pattern_names_are_distinct_options(coordinator, vendor):
    # Given the same pattern name saved in two folders.
    warm = {"id": "warm", "name": "Glamo WW", "colors": [255], "animation": "fade"}
    xmas = {"id": "xmas", "name": "Glamo WW", "colors": [65280], "animation": "chase"}
    coordinator._patterns = [
        {"folder": "Warm", "name": "Glamo WW", "data": warm},
        {"folder": "Holiday", "name": "Glamo WW", "data": xmas},
    ]
    select = GemstonePatternSelect(coordinator, "hub")
    # When the Holiday copy is chosen.
    await select.async_select_option("Glamo WW (Holiday)")
    # Then both are offered and exactly the chosen one plays and is shown as current.
    assert select.options == ["None", "Glamo WW (Holiday)", "Glamo WW (Warm)"]
    assert vendor.writes[-1][3]["pattern"]["id"] == "xmas"
    assert select.current_option == "Glamo WW (Holiday)"


async def test_commands_and_polls_do_not_rewrite_storage(loaded_entry):
    # Given a loaded controller.
    # When commands are sent and the controller is polled.
    with patch.object(loaded_entry._store, "async_save") as save:
        await loaded_entry.async_play_color("hub", 255, 80)
        await loaded_entry.async_set_speed("hub", 10)
        await loaded_entry.async_refresh()
    # Then nothing is written to disk.
    save.assert_not_called()


async def test_each_controller_keeps_its_own_post_command_refresh(coordinator, vendor):
    # Given two controllers.
    garage = {"id": "garage", "hub": {"localIp": "192.0.2.11"}}
    vendor.devices.append(garage)
    vendor.states["garage"] = {"onState": True, "color": 255}
    coordinator._known_devices.append(garage)
    coordinator._device_ids.append("garage")
    # When each receives a command.
    await coordinator.async_set_power("hub", False)
    await coordinator.async_set_power("garage", False)
    # Then each has its own scheduled hardware read-back.
    assert set(coordinator._refresh_cancel) == {"hub", "garage"}


async def test_diagnostics_redact_addresses(hass, entry, loaded_entry):
    # Given a loaded controller with a LAN address.
    # When diagnostics are downloaded.
    result = await async_get_config_entry_diagnostics(hass, entry)
    # Then they describe the controller without its address.
    text = json.dumps(result)
    assert "192.0.2.10" not in text
    assert result["devices"]["hub"]["transport"] == "local"


async def test_service_descriptions_match_registered_actions(hass, loaded_entry):
    # Given the integration's registered actions.
    registered = set(hass.services.async_services()["gemstone_lights"])
    # When the UI descriptions are read.
    described = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]
    # Then every action is described with the same fields in both places.
    assert registered == set(described) == set(strings)
    for name, spec in described.items():
        assert set(spec.get("fields") or {}) == set(strings[name].get("fields") or {})


async def test_library_action_targets_only_the_selected_zone(
    hass, loaded_entry, vendor
):
    # Given a downloaded library pattern and real zone entities.
    loaded_entry.library.folders = {
        "holidays / Christmas": [
            {"name": "Holiday", "data": {"colors": [255, 65280], "animation": "chase"}}
        ]
    }
    front = er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_zone_front"
    )
    # When the public action plays it on the front zone.
    await hass.services.async_call(
        "gemstone_lights",
        "play_library_pattern",
        {"entity_id": front, "pattern": "Holiday"},
        blocking=True,
    )
    # Then the complete palette reaches only the front zone.
    entries = {
        e["zoneId"]: e["pattern"]
        for e in vendor.writes[-1][3]["architectural"]["zonePatterns"]
    }
    assert entries["front"]["colors"] == [255, 65280]
    assert entries["back"]["colors"] == [255]


async def test_choosing_none_never_turns_the_lights_off(coordinator, vendor):
    # Given lights that are on.
    selects = [
        cls(coordinator, "hub")
        for cls in (
            GemstoneDesignSelect,
            GemstonePatternSelect,
            GemstoneLibraryPatternSelect,
        )
    ]
    # When an automation resets each dropdown to None.
    for select in selects:
        await select.async_select_option("None")
    # Then nothing is sent and the lights stay on.
    assert vendor.writes == []
    assert coordinator.device_state("hub")["onState"]
