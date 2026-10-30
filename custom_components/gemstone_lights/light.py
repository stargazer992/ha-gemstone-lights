"""Light platform for Gemstone Lights.

Two kinds of light are created per controller:

* one for the **whole run**, with colour, brightness and the controller's
  built-in animations exposed as Home Assistant effects, and
* one per **zone** (front upper, rear lower, ...), which behave like WLED
  segments and can each show their own colour and effect.

These are RGBW fixtures: the dedicated white channel is separate from the
red, green and blue ones.
"""

from __future__ import annotations

import difflib
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry
from .color_util import pack, unpack
from .const import EFFECT_LIST, EFFECT_SOLID
from .coordinator import GemstoneCoordinator
from .entity import GemstoneEntity


def _suggest(wanted: str, names: list[str]) -> str:
    """Return a short "did you mean" hint for a name that was not found.

    Substring matches come first because they are usually what was meant;
    close spellings fill any remaining places, so typos are caught too.
    """
    needle = wanted.casefold()
    hits = [name for name in names if needle in name.casefold()][:5]
    if len(hits) < 5:
        for name in difflib.get_close_matches(wanted, names, n=5, cutoff=0.6):
            if name not in hits:
                hits.append(name)
    hits = hits[:5]
    return f" Did you mean: {', '.join(hits)}?" if hits else ""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the whole-run light plus one light per zone.

    Zones are whatever the owner created in the Gemstone app, so the list is
    re-checked on every update and zones added later appear on their own.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new: list[LightEntity] = []
        for device_id in coordinator.device_ids:
            if device_id not in known:
                known.add(device_id)
                new.append(GemstoneLight(coordinator, device_id))
            for zone in coordinator.zones(device_id):
                zone_id = zone.get("id")
                if not zone_id or not zone.get("name"):
                    continue
                key = f"{device_id}:{zone_id}"
                if key not in known:
                    known.add(key)
                    new.append(GemstoneZoneLight(coordinator, device_id, zone_id))
        if new:
            async_add_entities(new)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class _GemstoneBaseLight(GemstoneEntity, LightEntity):
    """Shared colour and effect behaviour."""

    _attr_supported_color_modes = {ColorMode.RGBW}
    _attr_color_mode = ColorMode.RGBW
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = EFFECT_LIST

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise shared state."""
        super().__init__(coordinator, device_id)
        self._last_rgbw: tuple[int, int, int, int] = (255, 255, 255, 0)

    def _resolve(
        self, kwargs: dict[str, Any]
    ) -> tuple[tuple[int, int, int, int], int, str]:
        """Work out the colour, brightness and effect a command should apply."""
        rgbw = kwargs.get(ATTR_RGBW_COLOR) or self.rgbw_color or self._last_rgbw
        self._last_rgbw = tuple(rgbw)
        brightness = kwargs.get(ATTR_BRIGHTNESS) or self.brightness or 255
        effect = kwargs.get(ATTR_EFFECT) or self.effect or EFFECT_SOLID
        return tuple(rgbw), int(brightness), effect

    def _library_data(self, pattern: str, folder: str | None) -> dict[str, Any]:
        """Resolve a library name consistently for controller and zone actions."""
        data = self.coordinator.find_library_pattern(pattern, folder)
        if data is None:
            raise HomeAssistantError(
                f"No library pattern called '{pattern}'."
                + _suggest(pattern, self.coordinator.library_pattern_names())
            )
        return data


class GemstoneLight(_GemstoneBaseLight):
    """The whole light run."""

    _attr_name = None  # take the device name

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the light."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_light"

    @property
    def is_on(self) -> bool:
        """Return True when the lights are lit."""
        return bool(self._state.get("onState"))

    @property
    def _pattern(self) -> dict[str, Any] | None:
        return self._state.get("pattern") or None

    @property
    def _color_value(self) -> int | None:
        """Return the packed colour from either transport's field."""
        if isinstance(color_b := self._state.get("colorB"), dict):
            return color_b.get("value")
        return self._state.get("color")

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the current colour."""
        if pattern := self._pattern:
            colors = pattern.get("colors") or []
            return unpack(colors[0]) if colors else None
        return unpack(self._color_value)

    @property
    def brightness(self) -> int | None:
        """Return brightness, which the controller keeps separate."""
        if isinstance(color_b := self._state.get("colorB"), dict):
            return color_b.get("brightness")
        if pattern := self._pattern:
            return pattern.get("brightness")
        if (design := self._state.get("architectural")) and isinstance(design, dict):
            return design.get("brightness")
        return 255 if self.is_on else None

    @property
    def effect(self) -> str | None:
        """Return the active animation, or Solid for a plain colour."""
        if pattern := self._pattern:
            return pattern.get("animation") or EFFECT_SOLID
        if self._color_value is not None:
            return EFFECT_SOLID
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose transport and what design is playing."""
        design = self._state.get("architectural") or {}
        return {
            "playing_design": design.get("name"),
            "speed": self.coordinator.speed(self._device_id),
            "control": self.coordinator.control_transport(self._device_id),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally setting colour, brightness and effect."""
        if not kwargs:
            await self.coordinator.async_set_power(self._device_id, True)
            return

        # Only the brightness changed: dim what is playing rather than
        # replacing a saved pattern or design with a plain colour.
        if ATTR_RGBW_COLOR not in kwargs and ATTR_EFFECT not in kwargs:
            wanted = int(kwargs.get(ATTR_BRIGHTNESS) or self.brightness or 255)
            if await self.coordinator.async_set_brightness(self._device_id, wanted):
                return

        rgbw, brightness, effect = self._resolve(kwargs)

        if effect == EFFECT_SOLID:
            await self.coordinator.async_play_color(
                self._device_id, pack(*rgbw), brightness
            )
            return

        # Keep a multi-colour pattern's palette unless a colour was chosen.
        colors = [pack(*rgbw)]
        if ATTR_RGBW_COLOR not in kwargs and (playing := self._pattern):
            colors = list(playing.get("colors") or colors)

        pattern = self.coordinator.build_pattern(
            self._device_id, colors, effect, brightness=brightness
        )
        await self.coordinator.async_play_pattern(self._device_id, pattern)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lights off."""
        await self.coordinator.async_set_power(self._device_id, False)

    async def async_play_library_pattern(
        self, pattern: str, folder: str | None = None
    ) -> None:
        """Play a pattern from Gemstone's official library by name."""
        data = self._library_data(pattern, folder)
        await self.coordinator.async_play_pattern(self._device_id, data)


class GemstoneZoneLight(_GemstoneBaseLight):
    """One zone of the run, behaving like a WLED segment."""

    def __init__(
        self, coordinator: GemstoneCoordinator, device_id: str, zone_id: str
    ) -> None:
        """Initialise the zone light."""
        super().__init__(coordinator, device_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_zone_{zone_id}"

    @property
    def name(self) -> str | None:
        """Return the zone's name."""
        for zone in self.coordinator.zones(self._device_id):
            if zone.get("id") == self._zone_id:
                return zone.get("name")
        return None

    @property
    def available(self) -> bool:
        """Return False if the zone has been deleted."""
        return super().available and any(
            zone.get("id") == self._zone_id
            for zone in self.coordinator.zones(self._device_id)
        )

    @property
    def _zone(self) -> dict[str, Any] | None:
        """Return what this zone is showing, if anything."""
        return self.coordinator.zone_states(self._device_id).get(self._zone_id)

    @property
    def is_on(self) -> bool:
        """Return True when this zone is showing something."""
        return bool(self._state.get("onState")) and self._zone is not None

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return this zone's colour."""
        if zone := self._zone:
            return unpack(zone.get("color"))
        return None

    @property
    def brightness(self) -> int | None:
        """Return this zone's brightness."""
        return (self._zone or {}).get("brightness")

    @property
    def effect(self) -> str | None:
        """Return this zone's animation."""
        if zone := self._zone:
            return zone.get("animation") or EFFECT_SOLID
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the transport used for this zone's controller."""
        return {"control": self.coordinator.control_transport(self._device_id)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply a colour and effect to this zone only."""
        rgbw, brightness, effect = self._resolve(kwargs)
        spec = {}
        if ATTR_RGBW_COLOR in kwargs or self._zone is None:
            spec["color"] = pack(*rgbw)
        if ATTR_BRIGHTNESS in kwargs or self._zone is None:
            spec["brightness"] = brightness
        if ATTR_EFFECT in kwargs or self._zone is None:
            spec["animation"] = effect
        await self.coordinator.async_set_zone(
            self._device_id,
            self._zone_id,
            spec,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear this zone, leaving the others as they are."""
        await self.coordinator.async_set_zone(self._device_id, self._zone_id, None)

    async def async_play_library_pattern(
        self, pattern: str, folder: str | None = None
    ) -> None:
        """Play a complete library pattern in this zone only."""
        await self.coordinator.async_play_zone_pattern(
            self._device_id, self._zone_id, self._library_data(pattern, folder)
        )
