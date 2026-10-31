"""Local HTTP client for the Gemstone Hub2.

The controller exposes an unauthenticated HTTP API on port 80 once
"Allow Local Commands" is enabled in the Gemstone app. It is the same
interface the vendor's Control4 and Elan drivers use.

Using it avoids the round trip to Gemstone's cloud, so commands apply
immediately and keep working if the internet is down.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .const import (
    LOCAL_COMMAND_ATTEMPTS,
    LOCAL_MAX_PAYLOAD,
    LOCAL_ORIGIN,
    LOCAL_TIMEOUT,
)
from .validation import validate_state

_LOGGER = logging.getLogger(__name__)

# Only one of these may be active at a time; the rest are sent as null.
_MODES = ("colorB", "pattern", "architectural", "impulse", "playlist")


class GemstoneLocalError(Exception):
    """Raised when the controller cannot be reached or refuses a request."""


class GemstoneLocalApi:
    """Talks to a Hub2 directly over the LAN."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        """Initialise the client for one controller."""
        self._session = session
        self._host = host

    @property
    def host(self) -> str:
        """Return the controller's address."""
        return self._host

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"http://{self._host}{path}"
        try:
            async with self._session.get(
                url,
                headers={"Connection": "close"},
                timeout=aiohttp.ClientTimeout(total=LOCAL_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    raise GemstoneLocalError(f"GET {path} returned {resp.status}")
                body = json.loads(await resp.text())
                if not isinstance(body, dict):
                    raise GemstoneLocalError(f"GET {path} returned an invalid object")
                return body
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise GemstoneLocalError(f"Timeout on GET {path}") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise GemstoneLocalError(f"GET {path} failed: {err}") from err

    async def async_get_state(self) -> dict[str, Any]:
        """Return the controller's ``currentlyPlaying`` object."""
        body = await self._get("/device-state/currently-playing")
        try:
            return validate_state(body["state"]["reported"]["currentlyPlaying"])
        except (KeyError, TypeError, ValueError) as err:
            raise GemstoneLocalError(
                "Controller returned invalid playing state"
            ) from err

    async def async_get_settings(self) -> dict[str, Any]:
        """Return hub settings (firmware, pixel counts, outputs, ...)."""
        body = await self._get("/device-state/hub-settings")
        try:
            settings = body["state"]["reported"]["hubSettings"]
            if not isinstance(settings, dict):
                raise ValueError("Invalid settings")
            return settings
        except (KeyError, TypeError, ValueError) as err:
            raise GemstoneLocalError("Controller returned invalid settings") from err

    async def async_play(
        self, currently_playing: dict[str, Any], *, null_modes: bool = True
    ) -> None:
        """Send a ``currentlyPlaying`` object to the controller.

        With ``null_modes`` the unused modes are explicitly nulled, matching
        the vendor drivers, since the controller shows one mode at a time.
        Power changes pass ``null_modes=False`` so the hub keeps showing
        whatever it had.
        """
        payload = {**currently_playing}
        if null_modes:
            for mode in _MODES:
                payload.setdefault(mode, None)

        body = {
            "state": {"desired": {"currentlyPlaying": payload, "origin": LOCAL_ORIGIN}}
        }
        encoded = json.dumps(body)
        if len(encoded.encode()) > LOCAL_MAX_PAYLOAD:
            raise GemstoneLocalError("Payload exceeds the controller's 15 KiB limit")

        url = f"http://{self._host}/device-control/play"
        # Hubs occasionally stall for one request; every command sets a full
        # state, so sending it again after a timeout is harmless.
        for attempt in range(LOCAL_COMMAND_ATTEMPTS):
            try:
                async with self._session.post(
                    url,
                    data=encoded,
                    headers={"Content-Type": "application/json", "Connection": "close"},
                    timeout=aiohttp.ClientTimeout(total=LOCAL_TIMEOUT),
                ) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise GemstoneLocalError(
                            f"POST /device-control/play returned {resp.status}: "
                            f"{text[:160]}"
                        )
                    # The controller may reply with an empty or non-JSON body.
                    await resp.read()
                    return
            except (TimeoutError, asyncio.TimeoutError) as err:
                if attempt + 1 == LOCAL_COMMAND_ATTEMPTS:
                    raise GemstoneLocalError("Timeout sending command") from err
                _LOGGER.debug("Gemstone %s: command timed out, resending", self._host)
            except aiohttp.ClientError as err:
                raise GemstoneLocalError(f"Error sending command: {err}") from err

    async def async_set_power(self, on: bool) -> None:
        """Turn the lights on or off, keeping the current content."""
        await self.async_play({"onState": on}, null_modes=False)

    async def async_available(self) -> bool:
        """Return True when the controller answers locally."""
        try:
            await self.async_get_settings()
        except GemstoneLocalError:
            return False
        return True
