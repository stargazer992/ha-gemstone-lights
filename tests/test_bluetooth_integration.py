"""Bluetooth setup, entity lifecycle and transport changes in real HA code."""

import pytest

from .bluetooth_peer import ADDRESS, DEVICE


@pytest.fixture(autouse=True)
def bluetooth_discovery(monkeypatch):
    """Substitute only the external radio discovery at HA boundaries."""
    from custom_components.gemstone_lights import config_flow
    from custom_components.gemstone_lights import coordinator as coordinator_module

    def lookup(hass, address, *, connectable=True):
        return DEVICE if address == ADDRESS else None

    monkeypatch.setattr(config_flow, "async_ble_device_from_address", lookup)
    monkeypatch.setattr(coordinator_module, "async_ble_device_from_address", lookup)


async def test_bluetooth_setup_and_light_control_need_no_lan_or_account(
    hass, peripheral, http, enable_custom_integrations, mock_bluetooth
):
    # Given a discovered Hub2 with TCP local commands disabled and no cloud credentials.
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "bluetooth"}
    )
    # When it is configured over Bluetooth and a light action sets red at brightness 120.
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"bluetooth_address": ADDRESS.lower(), "name": "Bluetooth House"},
    )
    await hass.async_block_till_done()
    entry = result["result"]
    await hass.services.async_call(
        "light",
        "turn_on",
        {
            "entity_id": "light.bluetooth_house",
            "rgbw_color": [255, 0, 0, 0],
            "brightness": 120,
        },
        blocking=True,
    )
    # Then HA exposes the normal light, emits the RGBW state over BLE, and makes no HTTP request.
    assert entry.data["local_only"] is True
    assert "email" not in entry.data and "host" not in entry.data
    assert peripheral.state["colorB"] == {"value": 255, "brightness": 120}
    assert hass.states.get("light.bluetooth_house").attributes["control"] == "bluetooth"
    assert http.requests == {}
    assert peripheral.active == 0
    await hass.config_entries.async_unload(entry.entry_id)


async def test_switching_existing_controller_to_bluetooth_preserves_entities_and_content(
    hass, entry, loaded_entry, peripheral, http, mock_bluetooth
):
    # Given an existing controller with imported zones.
    original_entities = set(hass.states.async_entity_ids("light"))
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    # When Bluetooth replaces the LAN transport.
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"bluetooth_address": ADDRESS}
    )
    await hass.async_block_till_done()
    http.requests.clear()
    await entry.runtime_data.async_refresh()
    # Then identity and content survive while subsequent polling uses only Bluetooth.
    assert result["type"] == "create_entry"
    assert set(hass.states.async_entity_ids("light")) == original_entities
    assert {z["id"] for z in entry.runtime_data.zones("hub")} == {"front", "back"}
    assert entry.runtime_data.control_transport("hub") == "bluetooth"
    assert http.requests == {}


async def test_clearing_bluetooth_override_returns_existing_controller_to_lan(
    hass, entry, loaded_entry, peripheral, http, mock_bluetooth
):
    # Given an existing controller temporarily using Bluetooth through its options.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"bluetooth_address": ADDRESS}
    )
    await hass.async_block_till_done()
    used_connections = len(peripheral.connections)
    http.requests.clear()
    # When the Bluetooth address is cleared.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"bluetooth_address": ""}
    )
    await hass.async_block_till_done()
    # Then LAN polling resumes without another BLE connection or changed entity identity.
    assert entry.runtime_data.control_transport("hub") == "local"
    assert len(peripheral.connections) == used_connections
    assert {url.host for _, url in http.requests} == {"192.0.2.10"}


async def test_bluetooth_address_validation_precedes_radio_io(
    hass, peripheral, http, enable_custom_integrations, mock_bluetooth
):
    # Given a Bluetooth setup form containing a URL instead of a device address.
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "bluetooth"}
    )
    # When that value is submitted.
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"bluetooth_address": "http://example.invalid/"}
    )
    # Then field validation rejects it before any radio or HTTP operation.
    assert result["errors"] == {"bluetooth_address": "invalid_bluetooth_address"}
    assert peripheral.connections == []
    assert http.requests == {}


async def test_bluetooth_setup_rejects_unusable_state(
    hass, peripheral, http, enable_custom_integrations, mock_bluetooth
):
    # Given a controller returning a string instead of a boolean power state.
    peripheral.state = {"onState": "off"}
    flow = await hass.config_entries.flow.async_init(
        "gemstone_lights", context={"source": "user"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "bluetooth"}
    )
    # When its state is validated during setup.
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"bluetooth_address": ADDRESS}
    )
    # Then setup remains on the form and no incorrect light entity is created.
    assert result["errors"] == {"base": "cannot_connect_bluetooth"}
    assert not hass.states.async_entity_ids("light")
    assert peripheral.active == 0


async def test_rejected_bluetooth_command_keeps_connection_available_without_replay(
    hass, entry, loaded_entry, peripheral, http
):
    # Given an entry using Bluetooth whose controller rejects writes.
    from custom_components.gemstone_lights.api import GemstoneError

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"bluetooth_address": ADDRESS}
    )
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    before = dict(coordinator.device_state("hub"))
    peripheral.status = b"\x30\xe1"
    http.requests.clear()
    # When a power command receives the real firmware's negative acknowledgment.
    with pytest.raises(GemstoneError, match="status 225"):
        await coordinator.async_set_power("hub", False)
    # Then the requested state is not published or replayed and the controller stays local.
    assert coordinator.device_state("hub") == before
    assert coordinator.control_transport("hub") == "bluetooth"
    assert http.requests == {}
    assert peripheral.active == 0
