"""Zone composition: map controller output onto zones and back.

Zones come from the imported controller configuration (native firmware zones)
and from zones created in Home Assistant. Editing one zone always resends the
complete layout so neighboring zones keep their full patterns.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .animations import apply_animation
from .commands import serialized
from .const import EFFECT_SOLID
from .geometry import decode_lights
from .state import scale_color


class ZoneMixin:
    """Zone behaviour for the coordinator; relies on its state and commands."""

    @staticmethod
    def _zone_pixels(zones: list[dict[str, Any]]) -> dict[str, tuple[int, ...]]:
        """Return only verified complete selections, never guessed bounds."""
        result = {}
        for zone in zones:
            if not isinstance(zone.get("id"), str):
                continue
            try:
                result[zone["id"]] = decode_lights(zone.get("lights"))
            except ValueError:
                continue
        return result

    def zone_pixels(self, device_id: str) -> dict[str, tuple[int, ...]]:
        """Return each zone's ordered physical pixel selection."""
        return self._zone_pixels(self.zones(device_id))

    def zone_ranges(self, device_id: str) -> dict[str, tuple[int, int]]:
        """Return bounds only for contiguous zones; never flatten a gapped zone."""
        return {
            zid: (pixels[0], pixels[-1])
            for zid, pixels in self.zone_pixels(device_id).items()
            if pixels == tuple(range(pixels[0], pixels[-1] + 1))
        }

    def zone_states(self, device_id: str) -> dict[str, dict[str, Any]]:
        """Return what each zone is showing.

        Native zone designs carry ``zonePatterns``; pixel designs only report
        ``staticColors``, so those are mapped back onto zones by matching
        pixel ranges.
        """
        design = self.device_state(device_id).get("architectural") or {}

        if not design:
            if self.device_state(device_id).get("playlist") or self.device_state(
                device_id
            ).get("impulse"):
                return {}
            return {
                zone_id: {
                    "color": (entry["pattern"].get("colors") or [0])[0],
                    "brightness": entry["pattern"].get("brightness", 255),
                    "animation": entry["pattern"].get("animation", EFFECT_SOLID),
                }
                for zone_id, entry in self._zone_entries(device_id).items()
            }

        if zone_patterns := design.get("zonePatterns"):
            result: dict[str, dict[str, Any]] = {}
            for entry in zone_patterns:
                zone_id = entry.get("zoneId")
                pattern = entry.get("pattern") or {}
                colors = pattern.get("colors") or []
                if zone_id:
                    result[zone_id] = {
                        "color": colors[0] if colors else 0,
                        "brightness": round(
                            pattern.get("brightness", 255)
                            * design.get("brightness", 255)
                            / 255
                        ),
                        "animation": pattern.get("animation") or EFFECT_SOLID,
                    }
            return result

        static = design.get("staticColors") or []
        if not static:
            return {}

        result = {}
        brightness = design.get("brightness", 255)
        for zone_id, pixels in self.zone_pixels(device_id).items():
            for entry in static:
                lights = entry.get("lights") or []
                if not lights or entry.get("color") in (None, 0):
                    continue
                covered = set(lights)
                if all(pixel in covered for pixel in pixels):
                    result[zone_id] = {
                        "color": entry["color"],
                        "brightness": brightness,
                        "animation": EFFECT_SOLID,
                    }
                    break
        return result

    def _zone_entries(self, device_id: str) -> dict[str, dict[str, Any]]:
        """Keep complete vendor patterns and entry metadata for neighboring zones."""
        state = self.device_state(device_id)
        if state.get("onState") and (state.get("playlist") or state.get("impulse")):
            raise HomeAssistantError(
                "Stop the playlist or music mode before editing individual zones"
            )
        design = state.get("architectural") or {}
        if not design:
            state = self.device_state(device_id)
            pattern = state.get("pattern")
            if not pattern:
                color_b = state.get("colorB") or {}
                color = color_b.get("value", state.get("color"))
                if color is None:
                    return {}
                pattern = self.build_pattern(
                    device_id,
                    [color],
                    EFFECT_SOLID,
                    brightness=color_b.get("brightness", 255),
                )
            return {
                zone["id"]: {"zoneId": zone["id"], "pattern": deepcopy(pattern)}
                for zone in self.zones(device_id)
                if zone.get("id")
            }
        if design.get("zonePatterns") is not None:
            entries = {
                entry["zoneId"]: deepcopy(entry)
                for entry in design["zonePatterns"]
                if entry.get("zoneId") and isinstance(entry.get("pattern"), dict)
            }
            if design.get("brightness", 255) != 255:
                for entry in entries.values():
                    pattern = entry["pattern"]
                    pattern["brightness"] = round(
                        pattern.get("brightness", 255) * design["brightness"] / 255
                    )
            return entries
        if static := design.get("staticColors"):
            mapped = self.zone_states(device_id)
            selections = self.zone_pixels(device_id)
            represented = {pixel for zid in mapped for pixel in selections.get(zid, ())}
            lit = {
                pixel
                for item in static
                if item.get("color")
                for pixel in item.get("lights", [])
            }
            if not lit.issubset(represented):
                raise HomeAssistantError(
                    "This pixel design cannot be preserved as zones. Select a zone design before editing individual zones"
                )
        return {
            zone_id: {
                "zoneId": zone_id,
                "pattern": self.build_pattern(
                    device_id,
                    [spec["color"]],
                    spec["animation"],
                    brightness=spec["brightness"],
                ),
            }
            for zone_id, spec in self.zone_states(device_id).items()
        }

    async def _async_play_zones(
        self, device_id: str, entries: dict[str, dict[str, Any]]
    ) -> None:
        """Send the complete layout while preserving neighboring zone content."""
        if not entries:
            await self.async_set_power(device_id, False)
            return
        design = {
            "id": str(uuid.uuid4()),
            "name": "Home Assistant Zones",
            "brightness": 255,
            "preview": False,
            "zonePatterns": list(entries.values()),
        }
        await self.async_play_design(device_id, design)

    def _local_zone_design(
        self, device_id: str, design: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Render static palettes locally or use verified firmware-native animations."""
        selections = self.zone_pixels(device_id)
        patterns = {
            entry["zoneId"]: entry["pattern"] for entry in design["zonePatterns"]
        }
        if not patterns or not all(zid in selections for zid in patterns):
            raise HomeAssistantError(
                "Cannot determine the complete pixel layout for these zones"
            )
        if any(
            pattern.get("animation") not in (EFFECT_SOLID, "motionless")
            for pattern in patterns.values()
        ):
            # Hub2 1.1.5 was verified physically to render native zonePatterns
            # over LAN. Zone IDs must already belong to the controller (imported
            # from the account); HA-only ranges cannot create firmware zones.
            vendor_pixels = self._zone_pixels(self._zones.get(device_id, []))
            if all(vendor_pixels.get(zid) == selections[zid] for zid in patterns):
                return deepcopy(design)
            return None
        # Expand a motionless palette into explicit pixels. This works for
        # newly created HA-only zones as well as controller-defined zones.
        static = [
            {
                **deepcopy(item),
                "color": scale_color(item["color"], design.get("brightness", 255)),
            }
            for item in design.get("staticColors") or []
        ]
        for zid, pattern in patterns.items():
            colors = pattern.get("colors") or [0]
            groups: dict[int, list[int]] = {}
            for index, pixel in enumerate(selections[zid]):
                color = scale_color(
                    colors[index % len(colors)],
                    round(
                        pattern.get("brightness", 255)
                        * design.get("brightness", 255)
                        / 255
                    ),
                )
                groups.setdefault(color, []).append(pixel)
            static.extend(
                {"lights": lights, "color": color} for color, lights in groups.items()
            )
        return {
            "id": design.get("id") or str(uuid.uuid4()),
            "name": design.get("name") or "Home Assistant Zones",
            "preview": False,
            "brightness": 255,
            "staticColors": static,
        }

    @serialized
    async def async_play_zone_pattern(
        self, device_id: str, zone_id: str, pattern: dict[str, Any]
    ) -> None:
        """Play a saved palette in one zone without changing its neighbors."""
        if zone_id not in {z.get("id") for z in self.zones(device_id)}:
            raise HomeAssistantError("This zone no longer exists")
        desired = (
            self._zone_entries(device_id)
            if self.device_state(device_id).get("onState")
            else {}
        )
        desired[zone_id] = {"zoneId": zone_id, "pattern": deepcopy(pattern)}
        await self._async_play_zones(device_id, desired)

    @serialized
    async def async_set_zone(
        self, device_id: str, zone_id: str, spec: dict[str, Any] | None
    ) -> None:
        """Apply only the requested fields, preserving every other zone's content."""
        if zone_id not in {z.get("id") for z in self.zones(device_id)}:
            raise HomeAssistantError("This zone no longer exists")
        desired = self._zone_entries(device_id)
        if not self.device_state(device_id).get("onState") and spec is not None:
            desired = {zone_id: desired[zone_id]} if zone_id in desired else {}
        if spec is None:
            desired.pop(zone_id, None)
        else:
            entry = desired.get(
                zone_id,
                {
                    "zoneId": zone_id,
                    "pattern": self.build_pattern(device_id, [0xFFFFFF], EFFECT_SOLID),
                },
            )
            pattern = entry["pattern"]
            if "color" in spec:
                pattern["colors"] = [spec["color"]]
            if "brightness" in spec:
                pattern["brightness"] = spec["brightness"]
            if "animation" in spec:
                apply_animation(
                    pattern,
                    "motionless"
                    if spec["animation"] == EFFECT_SOLID
                    else spec["animation"],
                )
            desired[zone_id] = entry
        await self._async_play_zones(device_id, desired)
