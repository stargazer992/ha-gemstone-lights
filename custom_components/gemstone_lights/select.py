"""Select platform for Gemstone Lights.

Two dropdowns per controller:

* **Design** - saved architectural designs. These are the ones that can target
  individual zones (front upper, rear lower, ...), so this is how you drive
  front/back independently.
* **Pattern** - the saved patterns, applied to the whole controller.
* **Library folder / Library pattern** - Gemstone's official library, read
  from the files downloaded once to ``www/gemstones``.

Names are not unique (the same pattern can sit in two folders), so options get
a distinguishing suffix and are resolved back to the exact entry.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry
from .const import OPTION_NONE, OPTION_PICK_FOLDER
from .coordinator import GemstoneCoordinator
from .entity import GemstoneEntity, async_add_discovered_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the design and pattern selects."""
    async_add_discovered_entities(
        entry,
        async_add_entities,
        lambda coordinator, device_id: [
            GemstoneDesignSelect(coordinator, device_id),
            GemstonePatternSelect(coordinator, device_id),
            GemstoneLibraryFolderSelect(coordinator, device_id),
            GemstoneLibraryPatternSelect(coordinator, device_id),
        ],
    )


def labelled(
    entries: list[tuple[str, str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Give each (name, qualifier, content) a unique label, in display order."""
    names = Counter(name for name, _, _ in entries)
    labels = [
        f"{name} ({qualifier})" if names[name] > 1 and qualifier else name
        for name, qualifier, _ in entries
    ]
    seen: Counter[str] = Counter()
    totals = Counter(labels)
    result = []
    for label, (_, _, content) in zip(labels, entries, strict=True):
        if totals[label] > 1:
            seen[label] += 1
            label = f"{label} #{seen[label]}"
        result.append((label, content))
    return sorted(result, key=lambda item: item[0].casefold())


def playing_label(
    choices: list[tuple[str, dict[str, Any]]], playing: dict[str, Any]
) -> str:
    """Match what is playing by id first, then by its name."""
    if playing_id := playing.get("id"):
        for label, content in choices:
            if content.get("id") == playing_id:
                return label
    if name := playing.get("name"):
        for label, content in choices:
            if content.get("name") == name:
                return label
    return OPTION_NONE


class _GemstoneContentSelect(GemstoneEntity, SelectEntity):
    """Shared option handling for saved content."""

    _state_key: str

    def _choices(self) -> list[tuple[str, dict[str, Any]]]:
        raise NotImplementedError

    @property
    def options(self) -> list[str]:
        """Return unique labels for the saved content."""
        return [OPTION_NONE, *(label for label, _ in self._choices())]

    @property
    def current_option(self) -> str:
        """Return the content currently playing."""
        return playing_label(self._choices(), self._state.get(self._state_key) or {})

    async def _async_play(self, content: dict[str, Any]) -> None:
        raise NotImplementedError

    async def async_select_option(self, option: str) -> None:
        """Play the chosen content; None only reflects that nothing matches."""
        if option == OPTION_NONE:
            return
        for label, content in self._choices():
            if label == option:
                await self._async_play(content)
                return


class GemstoneDesignSelect(_GemstoneContentSelect):
    """Choose one of the saved (optionally per-zone) designs."""

    _attr_translation_key = "design"
    _attr_icon = "mdi:home-lightbulb-outline"
    _state_key = "architectural"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the select."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_design"

    def _choices(self) -> list[tuple[str, dict[str, Any]]]:
        return labelled(
            [
                (design["name"], "", design)
                for design in self.coordinator.designs(self._device_id)
                if design.get("name")
            ]
        )

    async def _async_play(self, content: dict[str, Any]) -> None:
        await self.coordinator.async_play_design(self._device_id, content)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the zones this controller has, for reference in automations."""
        zones = self.coordinator.zones(self._device_id)
        return {"zones": [zone.get("name") for zone in zones if zone.get("name")]}


class GemstonePatternSelect(_GemstoneContentSelect):
    """Choose one of the saved patterns."""

    _attr_translation_key = "pattern"
    _attr_icon = "mdi:palette"
    _state_key = "pattern"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the select."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_pattern"

    def _choices(self) -> list[tuple[str, dict[str, Any]]]:
        return labelled(
            [
                (pattern["name"], pattern.get("folder") or "", pattern["data"])
                for pattern in self.coordinator.patterns()
                if pattern.get("name") and isinstance(pattern.get("data"), dict)
            ]
        )

    async def _async_play(self, content: dict[str, Any]) -> None:
        await self.coordinator.async_play_pattern(self._device_id, content)


class GemstoneLibraryFolderSelect(GemstoneEntity, SelectEntity):
    """Browse the downloaded official pattern library by folder.

    The library runs to well over a thousand patterns, which is far too many
    for one dropdown, so this picks the folder and the companion select then
    offers just that folder's patterns. Choosing a folder changes nothing on
    the lights.
    """

    _attr_translation_key = "library_folder"
    _attr_icon = "mdi:folder-multiple"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the folder browser."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_library_folder"

    @property
    def options(self) -> list[str]:
        """Return every library folder."""
        return [OPTION_PICK_FOLDER, *self.coordinator.library_folder_options()]

    @property
    def current_option(self) -> str:
        """Return the folder being browsed."""
        chosen = self.coordinator.selected_folder(self._device_id)
        return chosen if chosen in self.options else OPTION_PICK_FOLDER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Report how much of the library is loaded."""
        return {"library_patterns": self.coordinator.library_size()}

    async def async_select_option(self, option: str) -> None:
        """Browse a folder."""
        self.coordinator.set_selected_folder(self._device_id, option)
        # Refresh the companion select so it offers this folder's patterns.
        self.coordinator.async_update_listeners()


class GemstoneLibraryPatternSelect(GemstoneEntity, SelectEntity):
    """Play a pattern from the folder being browsed."""

    _attr_translation_key = "library_pattern"
    _attr_icon = "mdi:playlist-music"

    def __init__(self, coordinator: GemstoneCoordinator, device_id: str) -> None:
        """Initialise the library pattern select."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_library_pattern"

    @property
    def options(self) -> list[str]:
        """Return the patterns in the folder being browsed."""
        return [
            OPTION_NONE,
            *self.coordinator.library_pattern_options(self._device_id),
        ]

    @property
    def current_option(self) -> str:
        """Return the playing pattern when it belongs to this folder."""
        playing = (self._state.get("pattern") or {}).get("name")
        return playing if playing in self.options else OPTION_NONE

    async def async_select_option(self, option: str) -> None:
        """Play the chosen library pattern; None changes nothing."""
        if option == OPTION_NONE:
            return

        folder = self.coordinator.selected_folder(self._device_id)
        data = self.coordinator.find_library_pattern(option, folder)
        if data:
            await self.coordinator.async_play_pattern(self._device_id, data)
