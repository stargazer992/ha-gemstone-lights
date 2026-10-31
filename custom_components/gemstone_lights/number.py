"""Number platform for Gemstone Lights."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry
from .coordinator import GemstoneCoordinator
from .entity import GemstoneEntity, async_add_discovered_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an animation speed control per controller."""
    async_add_discovered_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id: [GemstoneSpeed(coordinator, device_id)],
    )


class GemstoneSpeed(GemstoneEntity, NumberEntity):
    """Speed used when Home Assistant builds an animated pattern.

    The cloud does not report the speed of whatever is playing, so this holds
    the value Home Assistant will use for the next effect it sends. Changing it
    while an effect is running re-sends that effect immediately.
    """

    _attr_translation_key = "speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 1
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the speed control."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_speed"

    @property
    def native_value(self) -> float:
        """Return the configured speed."""
        return float(self.coordinator.speed(self._device_id))

    async def async_set_native_value(self, value: float) -> None:
        """Store the speed and re-apply any running effect."""
        await self.coordinator.async_set_speed(self._device_id, int(value))
