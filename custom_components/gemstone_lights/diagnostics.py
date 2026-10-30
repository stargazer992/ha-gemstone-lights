"""Diagnostics for Gemstone Lights, with addresses and secrets redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GemstoneConfigEntry
from .const import CONF_BLUETOOTH_ADDRESS, CONF_EMAIL, CONF_HOST, CONF_PASSWORD

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_HOST,
    CONF_BLUETOOTH_ADDRESS,
    "localIp",
    "host",
    "ssid",
    "wifiSsid",
    "wifiPassword",
    "macAddress",
    "mac",
    "serialNumber",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GemstoneConfigEntry
) -> dict[str, Any]:
    """Return what is needed to debug a controller, without addresses."""
    coordinator = entry.runtime_data
    devices = {}
    for device_id in coordinator.device_ids:
        devices[device_id] = {
            "info": coordinator.device_info_raw(device_id),
            "settings": coordinator.settings(device_id),
            "state": coordinator.device_state(device_id),
            "available": coordinator.device_available(device_id),
            "transport": coordinator.control_transport(device_id),
            "zones": coordinator.zones(device_id),
            "designs": len(coordinator.designs(device_id)),
        }
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "devices": devices,
            "patterns": len(coordinator.patterns()),
        },
        TO_REDACT,
    )
