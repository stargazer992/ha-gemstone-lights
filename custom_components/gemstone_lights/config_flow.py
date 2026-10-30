"""Config flow for Gemstone Lights."""

from __future__ import annotations

import ipaddress
import logging
import re
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

from .api import (
    GemstoneApi,
    GemstoneAuthError,
    GemstoneError,
    GemstoneRejectedError,
    async_fetch_account,
)
from .bluetooth_api import GemstoneBluetoothApi
from .const import (
    CONF_BLUETOOTH_ADDRESS,
    CONF_EMAIL,
    CONF_ENABLE_LOCAL,
    CONF_HOST,
    CONF_HOST_DEVICE,
    CONF_IMPORT,
    CONF_LOCAL_DEVICE,
    CONF_LOCAL_ONLY,
    CONF_PASSWORD,
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
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_BLUETOOTH_ADDRESS, default=""): str,
    }
)

_HUB_KEYS = ("pixelCount", "outputNames", "rgbwSequence", "tcpEnabled", "localIp")


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
    """Handle local, Bluetooth and one-time account-import setup."""

    VERSION = 2
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return GemstoneOptionsFlow()

    def __init__(self) -> None:
        """Initialise the flow."""
        self._api: GemstoneApi | None = None
        self._account: dict[str, Any] = {}
        self._enable_local = False
        self._device: dict[str, Any] = {}

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
        """Import a controller's setup and saved content from the account once."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = GemstoneApi(
                self.hass,
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL].strip(),
                user_input[CONF_PASSWORD],
            )
            try:
                account = await async_fetch_account(api)
            except GemstoneAuthError:
                errors["base"] = "invalid_auth"
            except GemstoneRejectedError as err:
                _LOGGER.warning("Gemstone cloud rejected the import: %s", err)
                errors["base"] = "cloud_rejected"
            except GemstoneError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error importing from Gemstone")
                errors["base"] = "unknown"
            else:
                configured = {
                    entry.unique_id for entry in self._async_current_entries()
                }
                account["devices"] = [
                    device
                    for device in account["devices"]
                    if device["id"] not in configured
                ]
                if not account["devices"]:
                    return self.async_abort(reason="no_new_controllers")
                self._api = api
                self._account = account
                self._enable_local = user_input.get(CONF_ENABLE_LOCAL, False)
                if len(account["devices"]) == 1:
                    return await self._async_import(account["devices"][0])
                return await self.async_step_controller()

        return self.async_show_form(
            step_id="cloud", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_controller(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which of the account's controllers to add."""
        devices = {device["id"]: device for device in self._account["devices"]}
        if user_input is not None:
            return await self._async_import(devices[user_input[CONF_HOST_DEVICE]])
        return self.async_show_form(
            step_id="controller",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST_DEVICE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": device_id,
                                    "label": d.get("name") or device_id,
                                }
                                for device_id, d in devices.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def _async_import(self, device: dict[str, Any]) -> ConfigFlowResult:
        """Prepare the chosen controller, then confirm its LAN address."""
        await self.async_set_unique_id(device["id"])
        self._abort_if_unique_id_configured()
        self._device = device
        hub = device.get("hub") or {}
        if hub.get("tcpEnabled") is False and self._enable_local and self._api:
            try:
                await self._api.async_set_local_enabled(device["id"], True)
            except GemstoneError as err:
                _LOGGER.warning(
                    "Gemstone %s: could not enable local commands (%s)",
                    device["id"],
                    err,
                )
            else:
                hub["tcpEnabled"] = True
        if host := hub.get("localIp"):
            if await self._async_reachable(host):
                return self._async_create_import(host)
        return await self.async_step_import_host()

    async def _async_reachable(self, host: str) -> bool:
        client = GemstoneLocalApi(async_get_clientsession(self.hass), host)
        try:
            self._device["settings"] = await client.async_get_settings()
            await client.async_get_state()
        except GemstoneLocalError:
            return False
        return True

    async def async_step_import_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address when the imported one cannot be reached."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            if not valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            elif await self._async_reachable(host):
                return self._async_create_import(host)
            else:
                errors["base"] = "cannot_connect_local"
        hub = self._device.get("hub") or {}
        return self.async_show_form(
            step_id="import_host",
            errors=errors,
            description_placeholders={
                "name": self._device.get("name") or self._device["id"]
            },
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=hub.get("localIp") or ""): str}
            ),
        )

    @callback
    def _async_create_import(self, host: str) -> ConfigFlowResult:
        """Create a local entry; the credentials are not kept."""
        device = self._device
        hub = device.get("hub") or {}
        settings = device.get("settings") or {}
        name = device.get("name") or f"Gemstone {host}"
        self._api = None
        return self.async_create_entry(
            title=name,
            data={
                CONF_LOCAL_ONLY: True,
                CONF_HOST: host,
                CONF_LOCAL_DEVICE: {
                    "id": device["id"],
                    "name": name,
                    "firmware": settings.get("firmware") or device.get("firmware"),
                    "hub": {
                        **{k: hub[k] for k in _HUB_KEYS if k in hub},
                        **{
                            k: settings[k]
                            for k in ("pixelCount", "rgbwSequence")
                            if k in settings
                        },
                        "localIp": host,
                    },
                },
                CONF_IMPORT: {
                    "zones": device.get("zones") or [],
                    "designs": device.get("designs") or [],
                    "patterns": self._account.get("patterns") or [],
                },
            },
        )


class GemstoneOptionsFlow(OptionsFlow):
    """Let the user change how the controller is reached."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the LAN address and Bluetooth override."""
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
            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(schema, user_input),
                    errors=errors,
                )
            return self.async_create_entry(
                data={
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
