"""Poll health sensors help spot an unreliable controller."""

from homeassistant.helpers import entity_registry as er

from custom_components.gemstone_lights.const import LOCAL_MISSED_POLLS


def entity_id(hass, domain, unique_id):
    return er.async_get(hass).async_get_entity_id(domain, "gemstone_lights", unique_id)


async def test_health_sensors_track_response_time_and_missed_polls(
    hass, loaded_entry, vendor
):
    # Given a loaded controller that answers normally.
    response = entity_id(hass, "sensor", "hub_response_time")
    missed = entity_id(hass, "sensor", "hub_missed_polls")
    light = entity_id(hass, "light", "hub_light")
    assert float(hass.states.get(response).state) >= 0
    assert hass.states.get(missed).state == "0"
    # When it misses enough polls in a row to become unavailable.
    vendor.failures["/device-state/currently-playing"] = 503
    for _ in range(LOCAL_MISSED_POLLS):
        await loaded_entry.async_refresh()
    await hass.async_block_till_done()
    # Then the misses stay visible while the light is unavailable.
    assert hass.states.get(light).state == "unavailable"
    assert hass.states.get(missed).state == str(LOCAL_MISSED_POLLS)
    assert hass.states.get(missed).attributes["consecutive"] == LOCAL_MISSED_POLLS
    assert hass.states.get(response).state == "unavailable"
    # When it answers again, the total is kept and the run resets.
    vendor.failures.clear()
    await loaded_entry.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(missed).state == str(LOCAL_MISSED_POLLS)
    assert hass.states.get(missed).attributes["consecutive"] == 0
    assert float(hass.states.get(response).state) >= 0
