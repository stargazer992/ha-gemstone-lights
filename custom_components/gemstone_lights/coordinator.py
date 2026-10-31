"""Data coordinator for Gemstone Lights.

Everything runs over the controller's local HTTP API or Bluetooth. The cloud
is only used once, during setup, to import the controller's configuration and
saved content; this module never contacts it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from time import monotonic
from typing import Any

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GemstoneApi, GemstoneError
from .bluetooth_api import GemstoneBluetoothApi, GemstoneBluetoothCommandError
from .catalog import LocalCatalog
from .commands import serialized
from .const import (
    CONF_IMPORT,
    CONF_LOCAL_DEVICE,
    DATA_DESIGNS,
    DATA_DEVICES,
    DATA_INFO,
    DATA_LOCAL,
    DATA_PATTERNS,
    DATA_SETTINGS,
    DATA_STATE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPEED,
    DOMAIN,
    EFFECT_SOLID,
    LOCAL_MISSED_POLLS,
    LOCAL_WRITE_GAP,
)
from .library import INDEX, PatternLibrary, library_path, write_library
from .local_api import GemstoneLocalApi, GemstoneLocalError
from .state import encode_cloud_design, same_content, scale_color
from .zones import ZoneMixin

_LOGGER = logging.getLogger(__name__)
_COMMAND_SETTLE_SECONDS = 5
_HUB_KEYS = ("localIp", "tcpEnabled", "pixelCount", "outputNames", "rgbwSequence")


class GemstoneCoordinator(ZoneMixin, DataUpdateCoordinator[dict[str, Any]]):
    """Poll controller state and keep the imported configuration and favorites."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        api: GemstoneApi | None = None,
        bluetooth_address: str | None = None,
        host_override: str | None = None,
        host_device_id: str | None = None,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.api = api
        self.catalog = LocalCatalog(self)
        self.library = PatternLibrary(hass)
        self._bluetooth_address = bluetooth_address
        self._host_override = host_override
        self._host_device_id = host_device_id
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}"
        )
        self._cache_lock = asyncio.Lock()
        self._saved_cache: dict[str, Any] | None = None

        # Imported once from the account; never refreshed from the cloud.
        self._known_devices: list[dict[str, Any]] = []
        self._device_ids: list[str] = []
        self._designs: dict[str, list[dict[str, Any]]] = {}
        self._patterns: list[dict[str, Any]] = []
        self._zones: dict[str, list[dict[str, Any]]] = {}

        # Runtime only: nothing below is persisted.
        self._speeds: dict[str, int] = {}
        self._selected_folder: dict[str, str] = {}
        self._write_locks: dict[str, asyncio.Lock] = {}
        self._write_owners: dict[str, asyncio.Task] = {}
        self._last_write: dict[str, float] = {}
        self._pending_states: dict[str, tuple[float, dict[str, Any]]] = {}
        self._state_aliases: dict[str, dict[str, Any]] = {}
        self._state_versions: dict[str, int] = {}
        self._refresh_cancel: dict[str, Any] = {}
        self._local: dict[str, GemstoneLocalApi | GemstoneBluetoothApi] = {}
        self._local_ok: dict[str, bool] = {}
        self._missed_polls: dict[str, int] = {}
        self._settings: dict[str, dict[str, Any]] = {}
        # Opt-in cloud access: which controllers were last read via the cloud.
        self._via_cloud: dict[str, bool] = {}
        self._last_reboot: dict[str, float] = {}

    # -- persistence ----------------------------------------------------------

    async def _async_setup(self) -> None:
        """Restore the imported configuration and favorites, then adopt a new import."""
        cached = await self._store.async_load()
        if not isinstance(cached, dict):
            cached = {}
        await self._async_move_cached_library(cached)
        await self.library.async_load()
        self.catalog.restore(cached.get("local_catalog"))
        devices = cached.get("devices")
        if not isinstance(devices, list) or any(
            not isinstance(d, dict) or not d.get("id") for d in devices
        ):
            devices = []
        if not devices and CONF_LOCAL_DEVICE in self.config_entry.data:
            devices = [deepcopy(self.config_entry.data[CONF_LOCAL_DEVICE])]
        self._known_devices = devices
        self._device_ids = [d["id"] for d in devices]
        for key in ("zones", "designs"):
            if isinstance(cached.get(key), dict):
                setattr(self, f"_{key}", cached[key])
        if isinstance(cached.get("patterns"), list):
            self._patterns = cached["patterns"]

        imported = self.config_entry.data.get(CONF_IMPORT)
        if isinstance(imported, dict) and self._device_ids:
            device_id = self._device_ids[0]
            self._zones[device_id] = list(imported.get("zones") or [])
            self._designs[device_id] = list(imported.get("designs") or [])
            self._patterns = list(imported.get("patterns") or [])
        # Rewrites older caches without the cloud-era runtime keys.
        await self._async_save_cache()
        if CONF_IMPORT in self.config_entry.data:
            data = dict(self.config_entry.data)
            data.pop(CONF_IMPORT)
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)

    async def _async_move_cached_library(self, cached: dict[str, Any]) -> None:
        """Move a library cached by older versions into www/gemstones once."""
        library, folders = cached.get("library"), cached.get("library_folders")
        if not isinstance(library, dict) or not isinstance(folders, dict):
            return
        path = library_path(self.hass)
        if await self.hass.async_add_executor_job((path / INDEX).exists):
            return
        try:
            count = await self.hass.async_add_executor_job(
                write_library, path, {"folders": folders, "patterns": library}
            )
        except (OSError, TypeError, KeyError, AttributeError) as err:
            _LOGGER.warning("Could not move the cached Gemstone library: %s", err)
            return
        _LOGGER.info("Moved %s cached library patterns to %s", count, path)

    async def _async_save_cache(self) -> None:
        """Persist only the controller setup and saved content, when it changed."""
        async with self._cache_lock:
            devices = []
            for device in self._known_devices:
                info = {k: device[k] for k in ("id", "name", "firmware") if k in device}
                hub = device.get("hub") or {}
                info["hub"] = {k: hub[k] for k in _HUB_KEYS if k in hub}
                devices.append(info)
            cached = deepcopy(
                {
                    "devices": devices,
                    "local_catalog": self.catalog.data,
                    "zones": self._zones,
                    "designs": self._designs,
                    "patterns": self._patterns,
                }
            )
            if cached != self._saved_cache:
                await self._store.async_save(cached)
                self._saved_cache = cached

    # -- basics -------------------------------------------------------------

    @asynccontextmanager
    async def _device_lock(self, device_id: str):
        """Serialize each device while allowing nested commands in the same task."""
        task = asyncio.current_task()
        if self._write_owners.get(device_id) is task:
            yield
            return
        lock = self._write_locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            self._write_owners[device_id] = task
            try:
                yield
            finally:
                self._write_owners.pop(device_id, None)

    async def async_shutdown(self) -> None:
        """Cancel delayed command refreshes on unload."""
        for cancel in self._refresh_cancel.values():
            cancel()
        self._refresh_cancel.clear()
        await super().async_shutdown()

    def _publish_command(
        self,
        device_id: str,
        state: dict[str, Any],
        wire_state: dict[str, Any] | None = None,
    ) -> None:
        """Publish a successful command immediately and protect it from stale echoes."""
        self._state_versions[device_id] = self._state_versions.get(device_id, 0) + 1
        self._pending_states[device_id] = (
            monotonic() + _COMMAND_SETTLE_SECONDS,
            deepcopy(state),
        )
        self._state_aliases[device_id] = {
            "logical": deepcopy(state),
            "wire": deepcopy(wire_state or state),
        }
        data = dict(self.data or {})
        records = dict(data.get(DATA_DEVICES, {}))
        records[device_id] = {
            **records.get(device_id, {}),
            DATA_STATE: deepcopy(state),
            "available": True,
        }
        data[DATA_DEVICES] = records
        self.async_set_updated_data(data)
        if cancel := self._refresh_cancel.pop(device_id, None):
            cancel()

        async def refresh(_now):
            self._refresh_cancel.pop(device_id, None)
            await self.async_request_refresh()

        # Read hardware after optimistic state protection expires; an earlier
        # refresh would merely republish the requested state, hiding mismatches.
        self._refresh_cancel[device_id] = async_call_later(
            self.hass, _COMMAND_SETTLE_SECONDS + 0.1, refresh
        )

    @property
    def device_ids(self) -> list[str]:
        """Return the known controller ids."""
        return self._device_ids

    def zones(self, device_id: str) -> list[dict[str, Any]]:
        """Return the zones configured on a controller."""
        return self.catalog.merge("zone", device_id, self._zones.get(device_id, []))

    def device_info_raw(self, device_id: str) -> dict[str, Any]:
        """Return the stored controller record."""
        return (
            (self.data or {})
            .get(DATA_DEVICES, {})
            .get(device_id, {})
            .get(DATA_INFO, {})
        )

    def device_state(self, device_id: str) -> dict[str, Any]:
        """Return the controller's currently-playing state."""
        return (
            (self.data or {})
            .get(DATA_DEVICES, {})
            .get(device_id, {})
            .get(DATA_STATE, {})
        )

    def designs(self, device_id: str) -> list[dict[str, Any]]:
        """Return saved designs for a controller."""
        return self.catalog.merge("design", device_id, self._designs.get(device_id, []))

    def patterns(self) -> list[dict[str, Any]]:
        """Return the saved patterns."""
        return self.catalog.merge("pattern", None, self._patterns)

    def library_folder_options(self) -> list[str]:
        """Return every downloaded library folder."""
        return self.library.folder_options()

    def selected_folder(self, device_id: str) -> str | None:
        """Return the library folder currently being browsed."""
        return self._selected_folder.get(device_id)

    def set_selected_folder(self, device_id: str, label: str) -> None:
        """Remember which library folder is being browsed."""
        self._selected_folder[device_id] = label

    def library_pattern_options(self, device_id: str) -> list[str]:
        """Return the patterns inside the folder being browsed."""
        return self.library.pattern_options(self._selected_folder.get(device_id))

    def find_library_pattern(
        self, name: str, folder_label: str | None = None
    ) -> dict[str, Any] | None:
        """Find a library pattern by name, optionally within one folder."""
        return self.library.find(name, folder_label)

    def library_pattern_names(self) -> list[str]:
        """Return every library pattern name (used for error hints)."""
        return self.library.names()

    def library_size(self) -> int:
        """Return how many library patterns are loaded."""
        return self.library.size()

    def settings(self, device_id: str) -> dict[str, Any]:
        """Return hub settings read from the controller."""
        return self._settings.get(device_id, {})

    def is_local(self, device_id: str) -> bool:
        """Return True when the last state read from this controller succeeded."""
        return bool(self._local_ok.get(device_id))

    def local_host(self, device_id: str) -> str | None:
        """Return the controller's local address, if known."""
        client = self._local.get(device_id)
        return client.host if isinstance(client, GemstoneLocalApi) else None

    async def async_follow_address(self, device_id: str, host: str) -> str | None:
        """Adopt the LAN address DHCP reported; return the address it replaced."""
        device = next(
            (d for d in self._known_devices if d.get("id") == device_id), None
        )
        if device is None or self.bluetooth_address(device_id):
            return None
        hub = device.setdefault("hub", {})
        override = bool(self._targets(device_id) and self._host_override)
        old = (self._host_override if override else None) or hub.get("localIp")
        if old == host:
            return None
        hub["localIp"] = host
        if override:
            self._host_override = host
        _LOGGER.info("Gemstone %s: following new address %s", device_id, host)
        await self._async_save_cache()
        await self.async_request_refresh()
        return old

    def bluetooth_address(self, device_id: str) -> str | None:
        """Return the explicitly selected Bluetooth address for this controller."""
        if self._targets(device_id):
            return self._bluetooth_address or None
        return None

    def control_transport(self, device_id: str) -> str:
        """Report the transport used for this controller."""
        if self._via_cloud.get(device_id):
            return "cloud"
        if isinstance(self._local.get(device_id), GemstoneBluetoothApi):
            return "bluetooth"
        return "local"

    def device_available(self, device_id: str) -> bool:
        """Use successful state reads only."""
        record = (self.data or {}).get(DATA_DEVICES, {}).get(device_id, {})
        return record.get("available", bool(record.get(DATA_STATE)))

    # -- transport ----------------------------------------------------------

    def _targets(self, device_id: str) -> bool:
        """Return True when the configured overrides belong to this controller."""
        return self._host_device_id == device_id or (
            not self._host_device_id and self._device_ids == [device_id]
        )

    def _local_client(
        self, device_id: str, info: dict[str, Any]
    ) -> GemstoneLocalApi | GemstoneBluetoothApi | None:
        """Return the Bluetooth or LAN client for a controller."""
        if address := self.bluetooth_address(device_id):
            existing = self._local.get(device_id)
            if (
                isinstance(existing, GemstoneBluetoothApi)
                and existing.address == address
            ):
                return existing
            client = GemstoneBluetoothApi(
                address,
                lambda: async_ble_device_from_address(
                    self.hass, address, connectable=True
                ),
            )
            self._local[device_id] = client
            return client

        override = self._host_override if self._targets(device_id) else None
        host = override or (info.get("hub") or {}).get("localIp")
        if not host:
            return None
        existing = self._local.get(device_id)
        if isinstance(existing, GemstoneLocalApi) and existing.host == host:
            return existing
        if existing is not None:
            _LOGGER.info("Gemstone %s: local address is now %s", device_id, host)
        client = GemstoneLocalApi(async_get_clientsession(self.hass), host)
        self._local[device_id] = client
        return client

    def _client(self, device_id: str) -> GemstoneLocalApi | GemstoneBluetoothApi:
        """Return the client for commands, even right after a failed poll."""
        info = next(
            (d for d in self._known_devices if d.get("id") == device_id),
            self.device_info_raw(device_id),
        )
        client = self._local.get(device_id) or self._local_client(device_id, info)
        if client is None:
            raise GemstoneError(
                "No LAN or Bluetooth address is configured for this controller"
            )
        return client

    async def _async_state_for(
        self, device_id: str, info: dict[str, Any]
    ) -> dict[str, Any]:
        """Read state from the controller, or the cloud when opted in."""
        client = self._local_client(device_id, info)
        try:
            if client is None:
                raise GemstoneLocalError(
                    "No LAN or Bluetooth address is configured for this controller"
                )
            state = await client.async_get_state()
        except GemstoneLocalError as err:
            self._local_ok[device_id] = False
            if self.api is None:
                raise GemstoneError(str(err)) from err
            if not self._via_cloud.get(device_id):
                _LOGGER.warning(
                    "Gemstone %s: controller unavailable locally (%s)", device_id, err
                )
            state = await self.api.async_get_state(device_id)
            self._via_cloud[device_id] = True
            return state
        self._via_cloud[device_id] = False
        if not self._local_ok.get(device_id):
            _LOGGER.info("Gemstone %s: connected via %s", device_id, client)
        self._local_ok[device_id] = True
        try:
            self._settings[device_id] = await client.async_get_settings()
        except GemstoneLocalError:
            pass
        return state

    # -- polling ------------------------------------------------------------

    async def _async_poll_device(
        self, device: dict[str, Any], versions: dict[str, int]
    ) -> dict[str, Any]:
        """Read one controller without blocking its commands during network I/O."""
        device_id = device["id"]
        available = True
        try:
            state = await self._async_state_for(device_id, device)
        except GemstoneError as err:
            missed = self._missed_polls.get(device_id, 0) + 1
            self._missed_polls[device_id] = missed
            state = self.device_state(device_id)
            available = bool(state) and missed < LOCAL_MISSED_POLLS
            if missed == LOCAL_MISSED_POLLS:
                _LOGGER.warning(
                    "Gemstone %s: controller unavailable after %d missed polls (%s)",
                    device_id,
                    missed,
                    err,
                )
            else:
                _LOGGER.debug("State fetch failed for %s: %s", device_id, err)
        else:
            self._missed_polls.pop(device_id, None)
            pending = self._pending_states.get(device_id)
            if pending and monotonic() < pending[0]:
                state = deepcopy(pending[1])
            elif self._state_versions.get(device_id, 0) == versions.get(device_id, 0):
                # A command completed while reading; its state is published.
                self._pending_states.pop(device_id, None)
                alias = self._state_aliases.get(device_id)
                if alias and same_content(state, alias["wire"]):
                    state = {
                        **deepcopy(alias["logical"]),
                        "onState": state["onState"],
                    }
                else:
                    self._state_aliases.pop(device_id, None)
        return {
            DATA_INFO: device,
            DATA_STATE: state,
            "available": available,
            DATA_LOCAL: self.is_local(device_id),
            DATA_SETTINGS: self._settings.get(device_id, {}),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll every controller in parallel."""
        devices = [d for d in self._known_devices if d.get("id")]
        self._device_ids = [d["id"] for d in devices]
        versions = dict(self._state_versions)
        records = await asyncio.gather(
            *(self._async_poll_device(device, versions) for device in devices)
        )
        result: dict[str, Any] = {
            DATA_DEVICES: {
                device["id"]: record
                for device, record in zip(devices, records, strict=True)
            },
            DATA_DESIGNS: self._designs,
            DATA_PATTERNS: self._patterns,
        }
        for device_id in result[DATA_DEVICES]:
            if self._state_versions.get(device_id, 0) != versions.get(device_id, 0):
                result[DATA_DEVICES][device_id] = self.data[DATA_DEVICES][device_id]
        return result

    # -- pattern construction ----------------------------------------------

    def speed(self, device_id: str) -> int:
        """Return the speed to use when building patterns."""
        return self._speeds.get(device_id, DEFAULT_SPEED)

    def set_speed(self, device_id: str, value: int) -> None:
        """Remember the desired animation speed."""
        self._speeds[device_id] = max(0, min(255, int(value)))

    @serialized
    async def async_set_speed(self, device_id: str, value: int) -> None:
        """Apply speed to active patterns, and only store it while off."""
        self.set_speed(device_id, value)
        state = self.device_state(device_id)
        if state.get("onState") and (pattern := state.get("pattern")):
            await self.async_play_pattern(
                device_id, {**pattern, "speed": self.speed(device_id)}
            )
        else:
            self.async_update_listeners()

    def build_pattern(
        self,
        device_id: str,
        colors: list[int],
        animation: str,
        *,
        name: str | None = None,
        brightness: int = 255,
    ) -> dict[str, Any]:
        """Build a pattern payload the controller accepts.

        The controller plays any well-formed pattern, saved or not, which is
        what makes free-form effect selection possible.
        """
        return {
            "id": str(uuid.uuid4()),
            "name": name or animation.replace("_", " ").title(),
            "colors": colors or [0xFFFFFF],
            "animation": "motionless" if animation == EFFECT_SOLID else animation,
            "speed": self.speed(device_id),
            "brightness": max(1, min(255, brightness)),
            "direction": 0,
            "backgroundColor": 0,
        }

    # -- commands -----------------------------------------------------------

    async def _async_command(
        self,
        device_id: str,
        send,
        state: dict[str, Any],
        wire_state: dict[str, Any] | None = None,
        cloud=None,
        cloud_state: dict[str, Any] | None = None,
    ) -> None:
        """Send a command over LAN or Bluetooth.

        Writes are serialised and spaced: the controller silently ignores
        commands that arrive back to back. A failed poll never blocks a
        command; the controller is always tried.
        """
        delay = LOCAL_WRITE_GAP - (monotonic() - self._last_write.get(device_id, 0))
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            if send is None:
                raise GemstoneLocalError("This command needs the Gemstone cloud")
            await send(self._client(device_id))
        except GemstoneBluetoothCommandError as err:
            raise GemstoneError(str(err)) from err
        except (GemstoneLocalError, GemstoneError) as err:
            if send is not None:
                _LOGGER.warning("Gemstone %s: command failed (%s)", device_id, err)
                self._local_ok[device_id] = False
            if self.api is None or cloud is None:
                raise GemstoneError(
                    f"The controller did not accept the command: {err}"
                ) from err
            await cloud()
            self._last_write[device_id] = monotonic()
            self._publish_command(device_id, state, cloud_state)
            return
        self._local_ok[device_id] = True
        self._missed_polls.pop(device_id, None)
        self._via_cloud[device_id] = False
        self._last_write[device_id] = monotonic()
        self._publish_command(device_id, state, wire_state)

    @serialized
    async def async_set_power(self, device_id: str, on: bool) -> None:
        """Turn a controller on or off."""
        wire = self._state_aliases.get(device_id, {}).get(
            "wire", self.device_state(device_id)
        )
        await self._async_command(
            device_id,
            lambda client: client.async_set_power(on),
            {**self.device_state(device_id), "onState": on},
            {**wire, "onState": on},
            lambda: self.api.async_set_power(device_id, on),
            {**wire, "onState": on},
        )

    @serialized
    async def async_play_color(
        self, device_id: str, packed: int, brightness: int
    ) -> None:
        """Show one solid colour; the controller keeps brightness separately."""
        state = {"onState": True, "colorB": {"value": packed, "brightness": brightness}}
        await self._async_command(
            device_id,
            lambda client: client.async_play(deepcopy(state)),
            state,
            cloud=lambda: self.api.async_play_color(
                device_id, scale_color(packed, brightness)
            ),
        )

    @serialized
    async def async_play_pattern(self, device_id: str, pattern: dict[str, Any]) -> None:
        """Play a pattern."""
        await self._async_command(
            device_id,
            lambda client: client.async_play({"onState": True, "pattern": pattern}),
            {"onState": True, "pattern": deepcopy(pattern)},
            cloud=lambda: self.api.async_play_pattern(device_id, pattern),
        )

    @serialized
    async def async_play_design(self, device_id: str, design: dict[str, Any]) -> None:
        """Play an architectural design."""
        payload = {**design, "preview": False}
        local_payload = (
            self._local_zone_design(device_id, payload)
            if payload.get("zonePatterns")
            else payload
        )
        if local_payload is None and self.api is None:
            raise HomeAssistantError(
                "Animated zones need zones imported from the controller with "
                "unchanged pixels; new or resized HA zones support motionless "
                "palettes only"
            )
        wire = {"onState": True, "architectural": local_payload}
        cloud_payload = encode_cloud_design(payload)
        cloud_reported = deepcopy(cloud_payload)
        for zone in cloud_reported.get("zonePatterns") or []:
            # Hub2 reports the master's level in each zone after cloud play.
            zone["pattern"]["brightness"] = cloud_reported.get("brightness", 255)
        await self._async_command(
            device_id,
            (lambda client: client.async_play(wire)) if local_payload else None,
            {"onState": True, "architectural": deepcopy(payload)},
            wire,
            lambda: self.api.async_play_design(device_id, cloud_payload),
            {"onState": True, "architectural": cloud_reported},
        )

    @serialized
    async def async_set_brightness(self, device_id: str, brightness: int) -> bool:
        """Dim or brighten whatever is playing without replacing it.

        A pattern or design carries its own brightness, so the same content is
        sent again with just that field changed. Returns False when a solid
        colour (or nothing) is playing, since that path is handled elsewhere.
        """
        state = self.device_state(device_id)
        brightness = max(1, min(255, int(brightness)))
        if pattern := state.get("pattern"):
            await self.async_play_pattern(
                device_id, {**pattern, "brightness": brightness}
            )
            return True
        if design := state.get("architectural"):
            await self.async_play_design(
                device_id, {**design, "brightness": brightness}
            )
            return True
        return False

    # -- opt-in cloud -----------------------------------------------------------

    @serialized
    async def async_soft_reboot(self, device_id: str) -> None:
        """Ask the cloud to soft reboot a controller; never repeated automatically."""
        if self.api is None:
            raise GemstoneError("Soft reboot needs cloud access, which is off")
        if monotonic() - self._last_reboot.get(device_id, float("-inf")) < 120:
            raise GemstoneError(
                "A reboot was recently requested; wait at least two minutes"
            )
        homegroup = None
        for group in await self.api.async_get_homegroups():
            if any(
                d.get("id") == device_id
                for d in await self.api.async_get_devices(group.get("id"))
            ):
                homegroup = group.get("id")
                break
        if homegroup is None:
            raise GemstoneError("This controller is not on the Gemstone account")
        self._last_reboot[device_id] = monotonic()
        self._pending_states.pop(device_id, None)
        await self.api.async_soft_reboot(device_id, homegroup)
        _LOGGER.warning("Gemstone %s: cloud soft reboot requested", device_id)

    async def async_reimport(
        self, device_id: str, device: dict[str, Any], patterns: list[dict[str, Any]]
    ) -> None:
        """Replace imported setup and saved content with a fresh account copy."""
        hub = device.get("hub") or {}
        for known in self._known_devices:
            if known["id"] == device_id:
                known.setdefault("hub", {}).update(
                    {k: hub[k] for k in _HUB_KEYS if k in hub}
                )
                if device.get("name"):
                    known["name"] = device["name"]
        self._zones[device_id] = list(device.get("zones") or [])
        self._designs[device_id] = list(device.get("designs") or [])
        self._patterns = list(patterns)
        await self._async_save_cache()
