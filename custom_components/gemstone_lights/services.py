"""Local editing, backups and playback actions."""

from __future__ import annotations

import json
import re
from pathlib import Path

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import service
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .catalog import checked_content
from .const import DOMAIN

BACKUP_DIR = "gemstone_backups"
_BACKUP_FILE = re.compile(r"[\w.-]+\.json")


def _write_backup(folder: Path, name: str, catalog: dict) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps(catalog, indent=2), encoding="utf-8")


def _read_backup(folder: Path, prefix: str, name: str | None) -> dict:
    if name is None:
        found = sorted(folder.glob(f"{prefix}-*.json")) if folder.is_dir() else []
        if not found:
            raise HomeAssistantError(f"No backup for this controller in {folder}")
        path = found[-1]
    elif _BACKUP_FILE.fullmatch(name):
        path = folder / name
    else:
        raise HomeAssistantError(f"Give a file name inside {folder}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise HomeAssistantError(f"No backup called {name} in {folder}") from err
    except ValueError as err:
        raise HomeAssistantError(f"{path.name} is not a valid backup") from err


_KIND = vol.In(["pattern", "design", "zone"])


def register_services(hass):
    """Expose catalog editing even while a controller is unavailable."""

    def controller(call):
        entity = er.async_get(hass).async_get(call.data["controller"])
        if entity and entity.platform == DOMAIN and entity.config_entry_id:
            entry = hass.config_entries.async_get_entry(entity.config_entry_id)
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator:
                for device_id in coordinator.device_ids:
                    if entity.unique_id == f"{device_id}_light":
                        return coordinator, device_id
        raise HomeAssistantError("Select a loaded Gemstone whole-controller light")

    async def reboot(call):
        coordinator, device_id = controller(call)
        await coordinator.async_soft_reboot(device_id)

    async def save(call):
        coordinator, device_id = controller(call)
        await coordinator.catalog.save(
            device_id,
            call.data["kind"],
            call.data["name"],
            call.data["content"],
            call.data.get("folder", ""),
        )

    async def delete(call):
        coordinator, device_id = controller(call)
        await coordinator.catalog.delete(
            device_id, call.data["kind"], call.data["name"]
        )

    async def export(call):
        coordinator, device_id = controller(call)
        return coordinator.catalog.export(device_id)

    async def import_data(call):
        coordinator, device_id = controller(call)
        await coordinator.catalog.import_data(device_id, call.data["catalog"])

    def backup_prefix(coordinator, device_id):
        name = coordinator.device_info_raw(device_id).get("name") or device_id
        return slugify(name) or slugify(device_id)

    async def backup(call):
        coordinator, device_id = controller(call)
        catalog = coordinator.catalog.export(device_id)
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        name = f"{backup_prefix(coordinator, device_id)}-{stamp}.json"
        folder = Path(hass.config.path(BACKUP_DIR))
        await hass.async_add_executor_job(_write_backup, folder, name, catalog)
        return {"file": name}

    async def restore(call):
        coordinator, device_id = controller(call)
        catalog = await hass.async_add_executor_job(
            _read_backup,
            Path(hass.config.path(BACKUP_DIR)),
            backup_prefix(coordinator, device_id),
            call.data.get("file"),
        )
        await coordinator.catalog.import_data(device_id, catalog)

    async def snapshot(call):
        coordinator, device_id = controller(call)
        state = coordinator.device_state(device_id)
        if content := state.get("architectural"):
            kind = "design"
        elif content := state.get("pattern"):
            kind = "pattern"
        elif (color := state.get("colorB")) or state.get("color") is not None:
            kind = "pattern"
            content = coordinator.build_pattern(
                device_id,
                [(color or {}).get("value", state.get("color"))],
                "motionless",
                brightness=(color or {}).get("brightness", 255),
            )
        else:
            raise HomeAssistantError(
                "The current mode cannot be saved as a pattern or design"
            )
        await coordinator.catalog.save(device_id, kind, call.data["name"], content)

    common = {vol.Required("controller"): cv.entity_id}
    for name, handler, fields, response in (
        ("soft_reboot", reboot, {}, SupportsResponse.NONE),
        (
            "save_content",
            save,
            {
                vol.Required("kind"): _KIND,
                vol.Required("name"): cv.string,
                vol.Required("content"): dict,
                vol.Optional("folder"): cv.string,
            },
            SupportsResponse.NONE,
        ),
        (
            "delete_content",
            delete,
            {vol.Required("kind"): _KIND, vol.Required("name"): cv.string},
            SupportsResponse.NONE,
        ),
        ("export_catalog", export, {}, SupportsResponse.ONLY),
        (
            "import_catalog",
            import_data,
            {vol.Required("catalog"): dict},
            SupportsResponse.NONE,
        ),
        ("backup_favorites", backup, {}, SupportsResponse.OPTIONAL),
        (
            "restore_favorites",
            restore,
            {vol.Optional("file"): cv.string},
            SupportsResponse.NONE,
        ),
        (
            "save_current",
            snapshot,
            {vol.Required("name"): cv.string},
            SupportsResponse.NONE,
        ),
    ):
        service.async_register_admin_service(
            hass, DOMAIN, name, handler, vol.Schema({**common, **fields}), response
        )

    async def play(entity, call):
        kind = call.data["kind"]
        content = checked_content(kind, call.data["content"])
        if hasattr(entity, "_zone_id"):
            if kind != "pattern":
                raise HomeAssistantError(
                    "A whole design must target the controller light"
                )
            await entity.coordinator.async_play_zone_pattern(
                entity._device_id, entity._zone_id, content
            )
        elif kind == "pattern":
            await entity.coordinator.async_play_pattern(entity._device_id, content)
        else:
            await entity.coordinator.async_play_design(entity._device_id, content)

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "play_content",
        entity_domain="light",
        schema={
            vol.Required("kind"): vol.In(["pattern", "design"]),
            vol.Required("content"): dict,
        },
        func=play,
    )
