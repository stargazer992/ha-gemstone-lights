"""Optional cloud: re-import and opt-in fallback through the real options flow."""

import pytest
from homeassistant.exceptions import HomeAssistantError


async def options_step(hass, entry, step, data):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": step}
    )
    result = await hass.config_entries.options.async_configure(flow["flow_id"], data)
    await hass.async_block_till_done()
    return result


CREDENTIALS = {"email": "test@example.invalid", "password": "test-password"}


async def test_reimport_refreshes_saved_patterns_without_keeping_password(
    hass, entry, loaded_entry, vendor, config_dir, cognito_external
):
    # Given the account now has a new saved pattern and a library folder.
    vendor.folders = [{"folderId": "warm", "name": "Warm"}]
    vendor.patterns = {
        "warm": [{"patternData": {"id": "ww", "name": "Glamo WW", "colors": [255]}}]
    }
    vendor.library_folders = [{"id": "lib", "folderName": "Xmas", "category": "x"}]
    vendor.library_patterns = [
        {
            "downloadableFolderId": "lib",
            "patternName": "Candy",
            "patternData": {"name": "Candy", "colors": [255]},
        }
    ]
    # When the user re-imports from the options menu.
    result = await options_step(hass, entry, "reimport", CREDENTIALS)
    # Then the pattern and library are refreshed and no credentials are kept.
    assert result["type"] == "create_entry"
    assert [p["name"] for p in entry.runtime_data.patterns()] == ["Glamo WW"]
    assert entry.runtime_data.find_library_pattern("Candy") is not None
    assert "password" not in entry.data and "password" not in entry.options
    assert not entry.options.get("cloud_access")


async def test_cloud_access_falls_back_when_lan_fails_and_off_deletes_credentials(
    hass, entry, loaded_entry, vendor, cognito_external
):
    # Given cloud access is switched on.
    await options_step(hass, entry, "cloud", {"cloud_access": True, **CREDENTIALS})
    coordinator = entry.runtime_data
    assert entry.options["password"] == "test-password"
    # When the controller stops answering locally and a command is sent.
    vendor.failures["/device-control/play"] = 503
    await coordinator.async_set_power("hub", False)
    # Then the command goes through the cloud.
    assert vendor.writes[-1][0] == "cloud"
    # And when cloud access is switched off, the credentials are deleted.
    await options_step(hass, entry, "cloud", {"cloud_access": False})
    assert "password" not in entry.options and "email" not in entry.options
    assert entry.runtime_data.api is None


async def test_without_cloud_access_failed_lan_command_is_not_replayed(
    loaded_entry, vendor
):
    # Given cloud access is off and the controller rejects LAN commands.
    vendor.failures["/device-control/play"] = 503
    # When a command is sent.
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await loaded_entry.async_set_power("hub", False)
    # Then nothing is sent to the cloud.
    assert all(write[0] == "local" for write in vendor.writes)


async def test_soft_reboot_needs_cloud_access(loaded_entry, vendor):
    # Given cloud access is off.
    # When a soft reboot is requested.
    with pytest.raises(HomeAssistantError, match="cloud access"):
        await loaded_entry.async_soft_reboot("hub")
    # Then no cloud request is made.
    assert vendor.writes == []
