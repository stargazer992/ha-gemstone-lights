"""Storage whose callers can rely on completed writes for recovery limits."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import CoreState
from homeassistant.helpers.storage import Store
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError


class GemstoneStore(Store[dict[str, Any]]):
    """Propagate write failures instead of treating a logged failure as success."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._save_lock = asyncio.Lock()

    async def async_save(self, data: dict[str, Any]) -> None:
        """Wait for an owned write even if the requesting action is cancelled."""
        task = self.hass.async_create_task(
            self._async_save_now(data), "Save Gemstone recovery and catalog state"
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # An executor write can outlive cancellation. Only a failed write
            # permits the caller to roll back its in-memory recovery record.
            await task
            raise

    async def _async_save_now(self, data: dict[str, Any]) -> None:
        # Store normally coalesces pending writes. Each recovery action needs
        # the result of its own snapshot, including its own write failure.
        async with self._save_lock:
            if self.hass.state is CoreState.stopping:
                raise OSError(
                    "Cannot confirm recovery storage while Home Assistant stops"
                )
            await super().async_save(data)

    async def _async_write_data(self, data: dict) -> None:
        """Keep HA's atomic write, but do not let Store swallow its errors."""
        try:
            await super()._async_write_data(data)
        except (WriteError, SerializationError) as err:
            raise OSError(
                "Could not persist Gemstone recovery and catalog state"
            ) from err
