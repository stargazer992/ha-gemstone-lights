"""Favorites can be backed up to a file and restored from it."""

import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er


def controller_entity(hass):
    return er.async_get(hass).async_get_entity_id(
        "light", "gemstone_lights", "hub_light"
    )


async def call(hass, action, **data):
    return await hass.services.async_call(
        "gemstone_lights",
        action,
        {"controller": controller_entity(hass), **data},
        blocking=True,
        return_response=action == "backup_favorites",
    )


@pytest.fixture
def config_dir(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    return tmp_path


async def test_backup_then_restore_brings_back_a_deleted_pattern(
    hass, loaded_entry, config_dir
):
    # Given a saved local pattern that is backed up to a file.
    await call(
        hass,
        "save_content",
        kind="pattern",
        name="Glamo WW",
        content={"colors": [255], "animation": "fade"},
    )
    response = await call(hass, "backup_favorites")
    path = config_dir / "gemstone_backups" / response["file"]
    assert response["file"].startswith("house-")
    assert "Glamo WW" in {p["name"] for p in json.loads(path.read_text())["patterns"]}
    # When the pattern is deleted and the newest backup is restored.
    await call(hass, "delete_content", kind="pattern", name="Glamo WW")
    assert "Glamo WW" not in {p["name"] for p in loaded_entry.patterns()}
    await call(hass, "restore_favorites")
    # Then the pattern is back.
    assert "Glamo WW" in {p["name"] for p in loaded_entry.patterns()}
    await call(hass, "restore_favorites", file=response["file"])


async def test_restore_rejects_paths_and_missing_files(hass, loaded_entry, config_dir):
    # Given no backups, restore fails clearly.
    with pytest.raises(HomeAssistantError, match="No backup"):
        await call(hass, "restore_favorites")
    # Paths outside the backup folder and unreadable files are refused.
    with pytest.raises(HomeAssistantError, match="file name"):
        await call(hass, "restore_favorites", file="../secrets.yaml")
    with pytest.raises(HomeAssistantError, match="No backup called"):
        await call(hass, "restore_favorites", file="other.json")
    (config_dir / "gemstone_backups").mkdir()
    (config_dir / "gemstone_backups" / "bad.json").write_text("{")
    with pytest.raises(HomeAssistantError, match="not a valid backup"):
        await call(hass, "restore_favorites", file="bad.json")
