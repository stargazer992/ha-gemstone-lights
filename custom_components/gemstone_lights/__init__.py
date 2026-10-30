"""The Gemstone Lights integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BLUETOOTH_ADDRESS,
    CONF_EMAIL,
    CONF_HOST,
    CONF_HOST_DEVICE,
    CONF_LOCAL_DEVICE,
    CONF_LOCAL_ONLY,
    CONF_PASSWORD,
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

_RUNTIME_OPTIONS = (CONF_HOST, CONF_BLUETOOTH_ADDRESS, CONF_HOST_DEVICE)

type GemstoneConfigEntry = ConfigEntry[GemstoneCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register actions even when no controller is currently loaded."""
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
    """Turn cloud-era entries into local entries that keep their cached content."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        # Credentials are no longer kept; cached controllers, zones, designs
        # and saved patterns stay in storage and remain usable over LAN.
        data = {
            k: v for k, v in entry.data.items() if k not in (CONF_EMAIL, CONF_PASSWORD)
        }
        data[CONF_LOCAL_ONLY] = True
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options={k: v for k, v in entry.options.items() if k in _RUNTIME_OPTIONS},
            version=2,
            minor_version=1,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GemstoneConfigEntry) -> bool:
    """Set up Gemstone Lights from a config entry."""
    coordinator = GemstoneCoordinator(
        hass,
        entry,
        bluetooth_address=entry.options.get(
            CONF_BLUETOOTH_ADDRESS, entry.data.get(CONF_BLUETOOTH_ADDRESS)
        ),
        host_override=entry.options.get(CONF_HOST) or entry.data.get(CONF_HOST),
        host_device_id=entry.options.get(CONF_HOST_DEVICE)
        or (entry.data.get(CONF_LOCAL_DEVICE) or {}).get("id"),
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
    """Remove persisted controller data when the entry is removed."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
