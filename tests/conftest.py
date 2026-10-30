"""Fixtures mock external I/O only; integration logic runs unchanged."""

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import ClientResponse
from aioresponses import aioresponses
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemstone_lights.api import GemstoneApi
from custom_components.gemstone_lights.coordinator import GemstoneCoordinator

from .vendor import Vendor

pytest_plugins = ["pytest_homeassistant_custom_component"]


class HTTPResponse(ClientResponse):
    """Bridge aioresponses 0.7.9 to aiohttp 3.14's new writer argument."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, stream_writer=SimpleNamespace(output_size=0), **kwargs)


@pytest.fixture
def http():
    """Intercept only HTTP requests; reject unregistered external access."""
    with (
        patch("aioresponses.core.ClientResponse", HTTPResponse),
        aioresponses() as mocked,
    ):
        yield mocked


LOCAL_DEVICE = {
    "id": "hub",
    "name": "House",
    "hub": {"localIp": "192.0.2.10", "tcpEnabled": True},
}


@pytest.fixture(autouse=True)
def config_dir(hass, tmp_path):
    """Keep files the integration writes (the pattern library) per test."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path


@pytest.fixture
def entry(hass):
    result = MockConfigEntry(
        domain="gemstone_lights",
        version=2,
        data={"local_only": True, "host": "192.0.2.10", "local_device": LOCAL_DEVICE},
        unique_id="hub",
    )
    result.add_to_hass(hass)
    return result


@pytest.fixture
async def api(hass):
    result = GemstoneApi(
        hass, async_get_clientsession(hass), "test@example.invalid", "test-password"
    )
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": time.time() + 3600}).encode()
    ).decode()
    result._store(
        {"access_token": f"header.{payload}.signature", "refresh_token": "refresh"}
    )
    return result


@pytest.fixture
def vendor(http):
    return Vendor(http)


@pytest.fixture
async def coordinator(hass, entry, vendor):
    result = GemstoneCoordinator(hass, entry, host_device_id="hub")
    result._known_devices = [dict(LOCAL_DEVICE)]
    result._device_ids = ["hub"]
    result._zones = {
        "hub": [
            {"id": "front", "name": "Front", "lights": [10, 11, 12]},
            {"id": "back", "name": "Back", "lights": [13, 14, 15]},
        ]
    }
    result.data = {
        "devices": {
            "hub": {
                "info": {"id": "hub", "name": "House", "online": True},
                "state": {"onState": True, "color": 255},
            }
        }
    }
    entry.runtime_data = result
    yield result
    await result.async_shutdown()


@pytest.fixture
def cognito_external(monkeypatch):
    """Replace the external Cognito SDK login, not the integration's auth logic."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def authenticate(user, password=None):
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": time.time() + 3600}).encode()
        ).decode()
        user.access_token = f"header.{payload}.signature"
        user.refresh_token = "refresh"
        user.id_token = user.access_token

    monkeypatch.setattr("pycognito.Cognito.authenticate", authenticate)
    monkeypatch.setattr("pycognito.Cognito.renew_access_token", authenticate)


@pytest.fixture
async def loaded_entry(hass, entry, vendor, hass_storage, enable_custom_integrations):
    """Load real platforms from a previously imported controller in HA storage."""
    key = f"gemstone_lights.{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"devices": vendor.devices, "zones": vendor.zones},
    }
    if not await hass.config_entries.async_setup(entry.entry_id):
        raise AssertionError("Integration setup failed")
    await hass.async_block_till_done()
    yield entry.runtime_data
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def peripheral(monkeypatch):
    """Replace only Bluetooth discovery and the external GATT connection."""
    from custom_components.gemstone_lights import bluetooth_api

    from .bluetooth_peer import Peripheral

    peer = Peripheral()
    monkeypatch.setattr(bluetooth_api, "establish_connection", peer.connect)

    return peer


@pytest.fixture
def bluetooth_client(peripheral):
    from custom_components.gemstone_lights.bluetooth_api import GemstoneBluetoothApi

    from .bluetooth_peer import ADDRESS, DEVICE

    return GemstoneBluetoothApi(ADDRESS, lambda: DEVICE)


@pytest.fixture(autouse=True)
def bluetooth_radio_environment(mock_bluetooth):
    """Keep HA's real Bluetooth manager while replacing operating-system radio I/O."""
    from unittest.mock import PropertyMock

    with patch(
        "bluetooth_adapters.systems.linux.LinuxAdapters.history",
        new_callable=PropertyMock,
        return_value={},
    ):
        yield
