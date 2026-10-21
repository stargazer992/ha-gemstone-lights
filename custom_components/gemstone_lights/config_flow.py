"""Config flow for Gemstone Lights."""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import GemstoneApi, GemstoneAuthError, GemstoneError
from .bluetooth_api import GemstoneBluetoothApi
from .const import (
    CONF_AUTO_RECOVERY,
    CONF_BLUETOOTH_ADDRESS,
    CONF_EMAIL,
    CONF_ENABLE_LIBRARY,
    CONF_ENABLE_LOCAL,
    CONF_HOST,
    CONF_HOST_DEVICE,
    CONF_LOCAL_DEVICE,
    CONF_LOCAL_ONLY,
    CONF_PASSWORD,
    CONF_PREFER_LOCAL,
    CONF_RECOVERY_COOLDOWN,
    CONF_RECOVERY_DELAY,
    DOMAIN,
)
from .local_api import GemstoneLocalApi, GemstoneLocalError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_ENABLE_LOCAL, default=False): bool,
    }
)


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LOCAL_ONLY, default=False): bool,
        vol.Optional(CONF_AUTO_RECOVERY, default=False): bool,
        vol.Optional(CONF_RECOVERY_DELAY, default=10): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=60)
        ),
        vol.Optional(CONF_RECOVERY_COOLDOWN, default=6): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=168)
        ),
        vol.Optional(CONF_PREFER_LOCAL, default=True): bool,
        vol.Optional(CONF_ENABLE_LOCAL, default=False): bool,
        vol.Optional(CONF_ENABLE_LIBRARY, default=True): bool,
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_BLUETOOTH_ADDRESS, default=""): str,
    }
)


def valid_host(host: str) -> bool:
    """Accept an IPv4 address or DNS hostname, never a URL or path."""
    try:
        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        return bool(
            not re.fullmatch(r"[0-9.]+", host)
            and re.fullmatch(
                r"(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host
            )
            and all(
                label
                and len(label) <= 63
                and not label.startswith("-")
                and not label.endswith("-")
                for label in host.split(".")
            )
        )


class GemstoneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, options and re-authentication."""

    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return GemstoneOptionsFlow()

    def __init__(self) -> None:
        """Initialise the flow."""
        self._reauth_email: str | None = None

    async def _async_validate(self, email: str, password: str) -> str | None:
        """Return an error key, or None when the credentials work."""
        api = GemstoneApi(
            self.hass, async_get_clientsession(self.hass), email, password
        )
        try:
            await api.async_login()
            await api.async_get_homegroups()
        except GemstoneAuthError:
            return "invalid_auth"
        except GemstoneError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Gemstone credentials")
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return await self.async_step_cloud(user_input)
        return self.async_show_menu(
            step_id="user", menu_options=["local", "bluetooth", "cloud"]
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect to an already provisioned controller without a Gemstone account."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            if not valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(f"local:{host}")
                self._abort_if_unique_id_configured()
                # Reject an address already attached to an account entry as well.
                for entry in self._async_current_entries():
                    coordinator = getattr(entry, "runtime_data", None)
                    if coordinator and any(
                        coordinator.local_host(device_id) == host
                        for device_id in coordinator.device_ids
                    ):
                        return self.async_abort(reason="already_configured")
                client = GemstoneLocalApi(async_get_clientsession(self.hass), host)
                try:
                    settings = await client.async_get_settings()
                    await client.async_get_state()
                except GemstoneLocalError:
                    errors["base"] = "cannot_connect_local"
                else:
                    name = user_input.get("name", "").strip() or f"Gemstone {host}"
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_LOCAL_ONLY: True,
                            CONF_HOST: host,
                            CONF_LOCAL_DEVICE: {
                                "id": f"local:{host}",
                                "name": name,
                                "firmware": settings.get("firmware"),
                                "hub": {
                                    **{
                                        k: settings[k]
                                        for k in (
                                            "pixelCount",
                                            "rgbwSequence",
                                            "pixelOutputNames",
                                        )
                                        if k in settings
                                    },
                                    "localIp": host,
                                    "tcpEnabled": True,
                                },
                            },
                        },
                    )
        return self.async_show_form(
            step_id="local",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional("name", default="Gemstone Lights"): str,
                }
            ),
        )

    async def async_step_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Read a provisioned controller directly through HA's Bluetooth adapters."""
        errors = {}
        if user_input is not None:
            address = user_input[CONF_BLUETOOTH_ADDRESS].strip().upper()
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_BLUETOOTH_ADDRESS] = "invalid_bluetooth_address"
            else:
                await self.async_set_unique_id(f"bluetooth:{address}")
                self._abort_if_unique_id_configured()
                for entry in self._async_current_entries():
                    if (
                        entry.options.get(
                            CONF_BLUETOOTH_ADDRESS,
                            entry.data.get(CONF_BLUETOOTH_ADDRESS),
                        )
                        == address
                    ):
                        return self.async_abort(reason="already_configured")
                client = GemstoneBluetoothApi(
                    address,
                    lambda: async_ble_device_from_address(
                        self.hass, address, connectable=True
                    ),
                )
                try:
                    settings = await client.async_get_settings()
                    await client.async_get_state()
                except GemstoneLocalError:
                    errors["base"] = "cannot_connect_bluetooth"
                else:
                    host = settings.get("localIp")
                    for entry in self._async_current_entries():
                        coordinator = getattr(entry, "runtime_data", None)
                        if (
                            host
                            and coordinator
                            and any(
                                coordinator.local_host(device_id) == host
                                for device_id in coordinator.device_ids
                            )
                        ):
                            return self.async_abort(reason="already_configured")
                    name = (
                        user_input.get("name", "").strip()
                        or settings.get("bluetoothName")
                        or "Gemstone Lights"
                    )
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_LOCAL_ONLY: True,
                            CONF_BLUETOOTH_ADDRESS: address,
                            CONF_LOCAL_DEVICE: {
                                "id": f"bluetooth:{address}",
                                "name": name,
                                "firmware": settings.get("firmware"),
                                "hub": {
                                    k: settings[k]
                                    for k in (
                                        "pixelCount",
                                        "rgbwSequence",
                                        "pixelOutputNames",
                                        "localIp",
                                        "tcpEnabled",
                                    )
                                    if k in settings
                                },
                            },
                        },
                    )
        return self.async_show_form(
            step_id="bluetooth",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BLUETOOTH_ADDRESS): str,
                    vol.Optional("name", default=""): str,
                }
            ),
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally import controllers and catalogs from an account."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            error = await self._async_validate(email, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    options={
                        CONF_ENABLE_LOCAL: user_input.get(CONF_ENABLE_LOCAL, False)
                    },
                )

        return self.async_show_form(
            step_id="cloud", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the stored password stops working."""
        self._reauth_email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = self._reauth_email or user_input.get(CONF_EMAIL, "")
            error = await self._async_validate(email, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": self._reauth_email or ""},
            errors=errors,
        )


class GemstoneOptionsFlow(OptionsFlow):
    """Let the user tune local control."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage local-control options."""
        errors = {}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        device_ids = coordinator.device_ids if coordinator else []
        options = [
            {
                "value": device_id,
                "label": coordinator.device_info_raw(device_id).get("name")
                or device_id,
            }
            for device_id in device_ids
        ]
        schema = (
            OPTIONS_SCHEMA.extend(
                {
                    vol.Optional(CONF_HOST_DEVICE): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            )
            if options
            else OPTIONS_SCHEMA
        )
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            address = (user_input.get(CONF_BLUETOOTH_ADDRESS) or "").strip().upper()
            selected = user_input.get(CONF_HOST_DEVICE) or ""
            if address and not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_BLUETOOTH_ADDRESS] = "invalid_bluetooth_address"
            if host or address:
                if host and not valid_host(host):
                    errors[CONF_HOST] = "invalid_host"
                if not selected and len(device_ids) == 1:
                    selected = device_ids[0]
                if not selected or selected not in device_ids:
                    errors[CONF_HOST_DEVICE] = "select_controller"
            local_only = self.config_entry.data.get(
                CONF_LOCAL_ONLY, False
            ) or user_input.get(CONF_LOCAL_ONLY, False)
            if (
                local_only
                and coordinator
                and any(
                    not (
                        ((host or address) and selected == device_id)
                        or coordinator.local_host(device_id)
                        or (
                            coordinator.bluetooth_address(device_id)
                            if CONF_BLUETOOTH_ADDRESS not in user_input
                            else None
                        )
                        or (
                            coordinator.device_info_raw(device_id).get("hub") or {}
                        ).get("localIp")
                    )
                    for device_id in device_ids
                )
            ):
                errors["base"] = "missing_local_address"
            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(schema, user_input),
                    errors=errors,
                )
            return self.async_create_entry(
                data={
                    CONF_LOCAL_ONLY: local_only,
                    CONF_AUTO_RECOVERY: user_input.get(CONF_AUTO_RECOVERY, False),
                    CONF_RECOVERY_DELAY: user_input.get(CONF_RECOVERY_DELAY, 10),
                    CONF_RECOVERY_COOLDOWN: user_input.get(CONF_RECOVERY_COOLDOWN, 6),
                    CONF_PREFER_LOCAL: local_only
                    or user_input.get(CONF_PREFER_LOCAL, True),
                    CONF_ENABLE_LOCAL: user_input.get(CONF_ENABLE_LOCAL, False),
                    CONF_ENABLE_LIBRARY: user_input.get(CONF_ENABLE_LIBRARY, True),
                    CONF_HOST: host,
                    CONF_BLUETOOTH_ADDRESS: address,
                    CONF_HOST_DEVICE: selected,
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    **{
                        key: self.config_entry.data[key]
                        for key in (CONF_HOST, CONF_BLUETOOTH_ADDRESS)
                        if key in self.config_entry.data
                    },
                    **self.config_entry.options,
                },
            ),
        )
