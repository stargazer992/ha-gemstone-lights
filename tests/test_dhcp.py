"""DHCP discovery keeps a controller reachable when its router address changes."""

from homeassistant.config_entries import SOURCE_DHCP
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo


async def discover(hass, hostname, ip):
    return await hass.config_entries.flow.async_init(
        "gemstone_lights",
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip=ip, hostname=hostname, macaddress="020000000001"),
    )


async def test_new_address_is_followed_and_kept(hass, entry, loaded_entry, vendor):
    # Given the controller moved to a new address on the router.
    vendor.devices[0]["hub"]["localIp"] = "192.0.2.20"
    # When DHCP discovery reports its hostname at that address.
    result = await discover(hass, "gemstone-hub", "192.0.2.20")
    await hass.async_block_till_done()
    # Then the entry is updated and commands reach the new address.
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.20"
    assert entry.data["local_device"]["hub"]["localIp"] == "192.0.2.20"
    coordinator = entry.runtime_data
    await coordinator.async_set_power("hub", False)
    assert coordinator.local_host("hub") == "192.0.2.20"
    assert not vendor.states["hub"]["onState"]


async def test_same_address_changes_nothing(hass, entry, loaded_entry):
    # Given DHCP reports the address already in use.
    before = dict(entry.data)
    result = await discover(hass, "gemstone-hub", "192.0.2.10")
    # Then nothing changes.
    assert result["reason"] == "already_configured"
    assert entry.data == before


async def test_unknown_controller_is_ignored(hass, loaded_entry):
    # Given a Gemstone hub that is not set up in Home Assistant.
    result = await discover(hass, "gemstone-h2-1094-zzzz", "192.0.2.30")
    # Then discovery stops without touching the configured entry.
    assert result["reason"] == "not_configured"
