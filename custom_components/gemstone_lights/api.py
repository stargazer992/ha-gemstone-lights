"""One-time import client for the Gemstone Lights cloud account.

The integration never uses the cloud at runtime. During setup only, it signs in
with AWS Cognito (SRP), reads the account's controllers, zones, designs and
saved patterns, and can switch on "Allow Local Commands" with consent. The
credentials are discarded afterwards.

Most endpoints expect ``deviceOrGroupId``; the architectural (per-zone)
endpoints expect ``deviceId``. Write calls use HTTP ``PUT``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import aiohttp
from botocore.config import Config
from botocore.exceptions import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    API_BASE_URL,
    APP_HEADERS,
    AWS_REGION,
    COGNITO_CLIENT_ID,
    COGNITO_USER_POOL_ID,
    REQUEST_TIMEOUT,
)
from .validation import validate_design, validate_pattern

_LOGGER = logging.getLogger(__name__)

# Refresh the access token this many seconds before it actually expires.
_TOKEN_LEEWAY = 120


class GemstoneError(HomeAssistantError):
    """Base error for this integration."""


class GemstoneAuthError(GemstoneError):
    """Raised when credentials are rejected."""


class GemstoneApiError(GemstoneError):
    """Raised when the API returns an unexpected response."""


class GemstoneRejectedError(GemstoneApiError):
    """Raised when the cloud refuses a request, e.g. an outdated app identity.

    The cloud only answers clients that present the mobile app's headers
    (``APP_HEADERS`` in const.py). Update those values when this persists.
    """


def _jwt_expiry(token: str) -> float:
    """Return the ``exp`` claim of a JWT, or 0 if it cannot be read."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:  # noqa: BLE001 - malformed token is not fatal
        return 0.0


class GemstoneApi:
    """Async client for the Gemstone Lights cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
    ) -> None:
        """Initialise the client."""
        self._hass = hass
        self._session = session
        self._email = email
        self._password = password

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._id_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    # -- authentication -----------------------------------------------------

    def _login_sync(self) -> dict[str, str]:
        """Perform a full SRP login. Runs in an executor (pycognito is sync)."""
        from pycognito import Cognito  # noqa: PLC0415 - imported lazily

        user = Cognito(
            COGNITO_USER_POOL_ID,
            COGNITO_CLIENT_ID,
            user_pool_region=AWS_REGION,
            username=self._email,
            botocore_config=Config(
                connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}
            ),
        )
        user.authenticate(password=self._password)
        return {
            "access_token": user.access_token,
            "refresh_token": user.refresh_token,
            "id_token": user.id_token,
        }

    def _store(self, tokens: dict[str, str]) -> None:
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens.get("refresh_token")
        self._id_token = tokens.get("id_token")
        self._expires_at = _jwt_expiry(self._access_token or "")

    async def async_login(self) -> None:
        """Log in with the configured credentials."""
        try:
            tokens = await self._hass.async_add_executor_job(self._login_sync)
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code")
            if code in {
                "NotAuthorizedException",
                "UserNotFoundException",
                "UserNotConfirmedException",
                "PasswordResetRequiredException",
            }:
                raise GemstoneAuthError(
                    "Gemstone rejected the account credentials"
                ) from err
            raise GemstoneApiError(
                "Gemstone authentication is temporarily unavailable"
            ) from err
        except Exception as err:
            raise GemstoneApiError(
                "Could not connect to Gemstone authentication"
            ) from err
        self._store(tokens)
        _LOGGER.debug("Gemstone login succeeded for %s", self._email)

    async def _async_ensure_token(self) -> None:
        """Sign in once; an import session never outlives its access token."""
        async with self._lock:
            if self._access_token and time.time() < self._expires_at - _TOKEN_LEEWAY:
                return
            await self.async_login()

    # -- transport ----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return the decoded ``data`` payload."""
        await self._async_ensure_token()

        access_token = self._access_token
        headers = {**APP_HEADERS, "authorization": f"Bearer {access_token}"}
        url = f"{API_BASE_URL}{path}"

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text()

                if resp.status in (401, 403):
                    raise GemstoneAuthError("Gemstone rejected the session")

                if 400 <= resp.status < 500:
                    raise GemstoneRejectedError(
                        f"{method} {path} returned HTTP {resp.status}: {text[:200]}"
                    )

                if resp.status >= 500:
                    raise GemstoneApiError(
                        f"{method} {path} returned HTTP {resp.status}: {text[:200]}"
                    )

                if not text:
                    if method == "GET":
                        raise GemstoneApiError(f"{path} returned an empty response")
                    return None
                try:
                    body = json.loads(text)
                except ValueError as err:
                    raise GemstoneApiError(
                        f"{method} {path} returned invalid JSON"
                    ) from err

                data = body.get("data") if isinstance(body, dict) else body
                if method == "GET":
                    if not isinstance(data, list) or any(
                        not isinstance(item, dict) for item in data
                    ):
                        raise GemstoneApiError(f"{path} returned an invalid catalog")
                    try:
                        for item in data:
                            if (
                                path == "/homegroup/devices"
                                and item.get("hub") is not None
                                and not isinstance(item["hub"], dict)
                            ):
                                raise ValueError("Invalid hub metadata")
                            if path == "/deviceControl/architectural/list":
                                validate_design(item)
                            if item.get("patternData") is not None:
                                validate_pattern(item["patternData"])
                    except ValueError as err:
                        raise GemstoneApiError(
                            f"{path} returned invalid catalog content"
                        ) from err
                return data
        except asyncio.TimeoutError as err:
            raise GemstoneApiError(f"Timeout calling {method} {path}") from err
        except aiohttp.ClientError as err:
            raise GemstoneApiError(f"Error calling {method} {path}: {err}") from err

    # -- read endpoints -----------------------------------------------------

    async def async_get_homegroups(self) -> list[dict[str, Any]]:
        """Return the homegroups belonging to the account."""
        return await self._request("GET", "/homegroup/list") or []

    async def async_get_devices(self, homegroup_id: str) -> list[dict[str, Any]]:
        """Return the controllers in a homegroup."""
        return (
            await self._request(
                "GET", "/homegroup/devices", params={"homegroupId": homegroup_id}
            )
            or []
        )

    async def async_get_zones(self, device_id: str) -> list[dict[str, Any]]:
        """Return the configured zones (e.g. Front Upper, Rear Lower)."""
        return (
            await self._request(
                "GET", "/deviceControl/zone/list", params={"deviceId": device_id}
            )
            or []
        )

    async def async_get_designs(self, device_id: str) -> list[dict[str, Any]]:
        """Return saved architectural designs (these can be per-zone)."""
        return (
            await self._request(
                "GET",
                "/deviceControl/architectural/list",
                params={"deviceId": device_id},
            )
            or []
        )

    async def async_get_folders(self) -> list[dict[str, Any]]:
        """Return the account's pattern folders."""
        return await self._request("GET", "/folders/list") or []

    async def async_get_folder_patterns(self, folder_id: str) -> list[dict[str, Any]]:
        """Return the patterns inside a folder."""
        return (
            await self._request(
                "GET", "/folders/pattern/list", params={"folderId": folder_id}
            )
            or []
        )

    # -- write endpoints (always PUT) --------------------------------------

    async def async_get_library_folders(self) -> list[dict[str, Any]]:
        """Return Gemstone's official pattern folders."""
        return (
            await self._request(
                "GET",
                "/downloads/folders/listGemstoneManaged",
                params={"page": 1, "pageSize": 500},
            )
            or []
        )

    async def async_get_library_patterns(self) -> list[dict[str, Any]]:
        """Return every pattern in Gemstone's official library.

        The endpoint pages; a short page means the end.
        """
        page_size = 750
        patterns: list[dict[str, Any]] = []
        for page in range(1, 21):
            batch = (
                await self._request(
                    "GET",
                    "/downloads/folders/pattern/listGemstoneManaged",
                    params={"page": page, "pageSize": page_size},
                )
                or []
            )
            patterns.extend(batch)
            if len(batch) < page_size:
                break
        return patterns

    async def async_set_local_enabled(self, device_id: str, enabled: bool) -> None:
        """Turn the controller's "Allow Local Commands" switch on or off.

        This is the same switch as Advanced Settings in the Gemstone app; the
        controller opens or closes its HTTP port in response.
        """
        await self._request(
            "PUT",
            "/deviceControl/deviceSettings",
            params={"deviceId": device_id},
            json_body={"tcpEnabled": enabled},
        )


async def async_fetch_account(api: GemstoneApi) -> dict[str, Any]:
    """Read everything worth keeping locally in one pass.

    Returns ``{"devices": [...], "patterns": [...]}``; each device carries its
    own ``zones`` and ``designs``. Saved patterns belong to the account.
    """
    devices: list[dict[str, Any]] = []
    for homegroup in await api.async_get_homegroups():
        if not (homegroup_id := homegroup.get("id")):
            continue
        for device in await api.async_get_devices(homegroup_id):
            if not (device_id := device.get("id")) or any(
                known["id"] == device_id for known in devices
            ):
                continue
            devices.append(
                {
                    **device,
                    "zones": await api.async_get_zones(device_id),
                    "designs": await api.async_get_designs(device_id),
                }
            )
    patterns: list[dict[str, Any]] = []
    for folder in await api.async_get_folders():
        if not (folder_id := folder.get("folderId")):
            continue
        for item in await api.async_get_folder_patterns(folder_id):
            data = item.get("patternData")
            if isinstance(data, dict) and data.get("name"):
                patterns.append(
                    {
                        "folder": folder.get("name") or "",
                        "name": data["name"],
                        "data": data,
                    }
                )
    return {"devices": devices, "patterns": patterns}


async def async_fetch_library(api: GemstoneApi) -> dict[str, Any]:
    """Read Gemstone's official library, grouped by folder, for one download."""
    folders = {
        folder["id"]: folder
        for folder in await api.async_get_library_folders()
        if folder.get("id")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in await api.async_get_library_patterns():
        folder_id = item.get("downloadableFolderId")
        data = item.get("patternData")
        name = item.get("patternName")
        if folder_id in folders and isinstance(data, dict) and name:
            grouped.setdefault(folder_id, []).append({"name": name, "data": data})
    return {"folders": folders, "patterns": grouped}
