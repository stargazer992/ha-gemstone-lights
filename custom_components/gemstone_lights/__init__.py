"""The Gemstone Lights integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import GemstoneApi
from .const import (
    CONF_AUTO_RECOVERY,
    CONF_BLUETOOTH_ADDRESS,
    CONF_EMAIL,
    CONF_ENABLE_LIBRARY,
    CONF_ENABLE_LOCAL,
    CONF_HOST,
    CONF_HOST_DEVICE,
    CONF_LOCAL_DEVICE,
    CONF_LOCAL_ONLY,
    CONF_PASSWORD,
    CONF_PREFER_LOCAL,
    CONF_RECOVERY_COOLDOWN,
    CONF_RECOVERY_DELAY,
    DOMAIN,
)
from .coordinator import GemstoneCoordinator
from .services import register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

type GemstoneConfigEntry = ConfigEntry[GemstoneCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the library action even when no account is currently loaded."""
    register_services(hass)
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "play_library_pattern",
        entity_domain="light",
        schema={vol.Required("pattern"): cv.string, vol.Optional("folder"): cv.string},
        func="async_play_library_pattern",
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> bool:
    """Require explicit consent after the previous auto-enable default."""
    if entry.version > 1:
        return False
    if entry.version == 1 and entry.minor_version < 2:
        # Older options forms saved True by default, so that value cannot prove
        # consent. Reset only this integration option, never the device setting.
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_ENABLE_LOCAL: False},
            minor_version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> bool:
    """Set up Gemstone Lights from a config entry."""
    local_only = entry.data.get(CONF_LOCAL_ONLY, False) or entry.options.get(
        CONF_LOCAL_ONLY, False
    )
    api = (
        None
        if local_only
        else GemstoneApi(
            hass,
            async_get_clientsession(hass),
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )
    )

    coordinator = GemstoneCoordinator(
        hass,
        entry,
        api,
        bluetooth_address=entry.options.get(
            CONF_BLUETOOTH_ADDRESS, entry.data.get(CONF_BLUETOOTH_ADDRESS)
        ),
        host_override=entry.options.get(CONF_HOST) or entry.data.get(CONF_HOST),
        host_device_id=entry.options.get(CONF_HOST_DEVICE)
        or (entry.data.get(CONF_LOCAL_DEVICE) or {}).get("id"),
        prefer_local=entry.options.get(CONF_PREFER_LOCAL, True),
        enable_local=entry.options.get(CONF_ENABLE_LOCAL, False),
        enable_library=entry.options.get(CONF_ENABLE_LIBRARY, True),
        auto_recovery=entry.options.get(CONF_AUTO_RECOVERY, False),
        recovery_delay_minutes=entry.options.get(CONF_RECOVERY_DELAY, 10),
        recovery_cooldown_hours=entry.options.get(CONF_RECOVERY_COOLDOWN, 6),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> None:
    """Remove persisted controller metadata when the account is removed."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
