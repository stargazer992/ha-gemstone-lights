"""An account-wide legacy override must never redirect another controller."""


async def test_ambiguous_legacy_override_cannot_redirect_other_controller(
    coordinator, vendor
):
    # Given two controllers and an old account-wide host override with no device selection.
    garage = {
        "id": "other",
        "name": "Garage",
        "hub": {"localIp": "192.0.2.11", "tcpEnabled": True},
    }
    vendor.devices.append(garage)
    coordinator._known_devices.append(garage)
    coordinator._host_device_id = None
    vendor.states["other"] = {"onState": True, "color": 65280}
    coordinator._host_override = "192.0.2.10"
    coordinator.data = await coordinator._async_update_data()
    # When the garage is switched off.
    await coordinator.async_set_power("other", False)
    # Then the request reaches the garage's discovered address and leaves the house on.
    assert vendor.writes[-1][0:2] == ("local", "other")
    assert vendor.states["hub"]["onState"]
    assert not vendor.states["other"]["onState"]


async def test_options_reject_url_and_bind_valid_host_to_controller(
    hass, entry, coordinator, enable_custom_integrations
):
    # Given an account with one known controller and its real Home Assistant options flow.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "connection"}
    )
    # When a URL is submitted in place of a host, then a plain hostname is submitted.
    rejected = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"host": "http://192.0.2.10/path"}
    )
    accepted = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"host": "controller.local"}
    )
    # Then invalid input gets a field error and the accepted override is explicitly bound to the hub.
    assert rejected["errors"] == {"host": "invalid_host"}
    assert accepted["data"]["host"] == "controller.local"
    assert accepted["data"]["host_device_id"] == "hub"
