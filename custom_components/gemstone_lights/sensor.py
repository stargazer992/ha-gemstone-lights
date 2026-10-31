"""Sensor platform for Gemstone Lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
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
    """Set up "now playing" and poll health sensors per controller."""
    async_add_discovered_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id: [
            GemstoneNowPlaying(coordinator, device_id),
            GemstoneResponseTime(coordinator, device_id),
            GemstoneMissedPolls(coordinator, device_id),
        ],
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


class GemstoneResponseTime(GemstoneEntity, SensorEntity):
    """How long the controller took to answer the last local status read."""

    _attr_translation_key = "response_time"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_response_time"

    @property
    def native_value(self) -> float | None:
        """Return the last response time, or unknown after a failed read."""
        return self.coordinator.health(self._device_id)["response_ms"]


class GemstoneMissedPolls(GemstoneEntity, SensorEntity):
    """Count failed status reads since Home Assistant started."""

    _attr_translation_key = "missed_polls"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_missed_polls"

    @property
    def available(self) -> bool:
        """Stay available while the controller is not, to show the misses."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> int:
        """Return the number of missed polls."""
        return self.coordinator.health(self._device_id)["missed_polls"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the current run of consecutive misses."""
        return {
            "consecutive": self.coordinator.health(self._device_id)[
                "consecutive_missed"
            ]
        }
