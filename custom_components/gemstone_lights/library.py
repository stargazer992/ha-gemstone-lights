"""Gemstone's official pattern library, kept as files in ``www/gemstones``.

The library is downloaded once during the account import. Home Assistant
reads it from these files afterwards, so it never needs the cloud and the
integration's own storage holds only the controller setup and favorites.
Anything under ``www`` is served without login at ``/local/``; patterns are
not sensitive.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .catalog import checked_content

_LOGGER = logging.getLogger(__name__)

LIBRARY_DIR = ("www", "gemstones")
INDEX = "index.json"


def library_path(hass: HomeAssistant) -> Path:
    """Return the library directory inside the HA configuration folder."""
    return Path(hass.config.path(*LIBRARY_DIR))


def folder_label(folder: dict[str, Any]) -> str:
    """Return a readable "category / folder" label."""
    name = folder.get("folderName") or "Unknown"
    category = (folder.get("category") or "other").replace("-", " ")
    return f"{category} / {name}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "folder"


def write_library(path: Path, library: dict[str, Any]) -> int:
    """Write one file per folder plus an index; return the pattern count."""
    path.mkdir(parents=True, exist_ok=True)
    index = []
    used: set[str] = set()
    total = 0
    for folder_id, folder in library["folders"].items():
        patterns = sorted(
            library["patterns"].get(folder_id, []), key=lambda p: p["name"].casefold()
        )
        if not patterns:
            continue
        label = folder_label(folder)
        name = _slug(label)
        while f"{name}.json" in used:
            name += "-1"
        filename = f"{name}.json"
        used.add(filename)
        (path / filename).write_text(
            json.dumps({"id": folder_id, "label": label, "patterns": patterns}),
            encoding="utf-8",
        )
        index.append({"id": folder_id, "label": label, "file": filename})
        total += len(patterns)
    (path / INDEX).write_text(
        json.dumps({"version": 1, "folders": index}, indent=1), encoding="utf-8"
    )
    return total


def read_library(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Return ``{label: patterns}``, skipping files that are missing or invalid."""
    try:
        index = json.loads((path / INDEX).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        _LOGGER.warning("Gemstone library index unreadable: %s", err)
        return {}
    library: dict[str, list[dict[str, Any]]] = {}
    for entry in index.get("folders") or []:
        try:
            file = path / Path(entry["file"]).name
            content = json.loads(file.read_text(encoding="utf-8"))
            patterns = []
            for item in content["patterns"]:
                if isinstance(item.get("name"), str):
                    patterns.append(
                        {
                            "name": item["name"],
                            "data": checked_content("pattern", item["data"]),
                        }
                    )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
            _LOGGER.warning("Skipping Gemstone library file %s: %s", entry, err)
            continue
        except Exception as err:  # noqa: BLE001 - one bad pattern skips its folder
            _LOGGER.warning("Skipping Gemstone library file %s: %s", entry, err)
            continue
        library[str(entry.get("label") or file.stem)] = patterns
    return library


class PatternLibrary:
    """In-memory view of the library files, loaded at setup."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self.folders: dict[str, list[dict[str, Any]]] = {}

    async def async_load(self) -> None:
        """Read the library files without blocking the event loop."""
        self.folders = await self._hass.async_add_executor_job(
            read_library, library_path(self._hass)
        )

    def folder_options(self) -> list[str]:
        return sorted(label for label, items in self.folders.items() if items)

    def pattern_options(self, label: str | None) -> list[str]:
        return [p["name"] for p in self.folders.get(label or "", [])]

    def find(self, name: str, label: str | None = None) -> dict[str, Any] | None:
        wanted = name.strip().casefold()
        for folder, patterns in self.folders.items():
            if label and folder != label:
                continue
            for pattern in patterns:
                if pattern["name"].casefold() == wanted:
                    return pattern["data"]
        return None

    def names(self) -> list[str]:
        return [p["name"] for patterns in self.folders.values() for p in patterns]

    def size(self) -> int:
        return sum(len(patterns) for patterns in self.folders.values())
