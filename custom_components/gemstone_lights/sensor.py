"""Sensor platform for Gemstone Lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry
from .color_util import unpack
from .coordinator import GemstoneCoordinator
from .entity import GemstoneEntity, async_add_discovered_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a "now playing" sensor per controller."""
    async_add_discovered_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id: [GemstoneNowPlaying(coordinator, device_id)],
    )


class GemstoneNowPlaying(GemstoneEntity, SensorEntity):
    """Report what the controller is showing right now."""

    _attr_translation_key = "now_playing"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_now_playing"

    @property
    def native_value(self) -> str:
        """Return a short description of the current output."""
        state = self._state
        if not state.get("onState"):
            return "Off"
        if design := (state.get("architectural") or {}).get("name"):
            return design
        if pattern := (state.get("pattern") or {}).get("name"):
            return pattern
        color = state.get("color")
        if isinstance(color_b := state.get("colorB"), dict):
            color = color_b.get("value")
        if color is not None:
            red, green, blue, white = unpack(color) or (0, 0, 0, 0)
            return f"#{red:02X}{green:02X}{blue:02X}" + (f"+W{white}" if white else "")
        return "On"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the underlying detail."""
        state = self._state
        info = self._info
        hub = info.get("hub") or {}
        settings = self.coordinator.settings(self._device_id)
        color = state.get("color")
        if isinstance(color_b := state.get("colorB"), dict):
            color = color_b.get("value")
        return {
            "on_state": state.get("onState"),
            "design": (state.get("architectural") or {}).get("name"),
            "pattern": (state.get("pattern") or {}).get("name"),
            "color": color,
            "control": self.coordinator.control_transport(self._device_id),
            "local_ip": self.coordinator.local_host(self._device_id)
            or hub.get("localIp"),
            "firmware": settings.get("firmware") or info.get("firmware"),
            "outputs": settings.get("pixelOutputNames") or hub.get("outputNames"),
            "pixel_count": settings.get("pixelCount") or hub.get("pixelCount"),
            "rgbw_sequence": settings.get("rgbwSequence") or hub.get("rgbwSequence"),
        }
