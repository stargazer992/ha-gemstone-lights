"""Run entity setup through real Home Assistant platforms."""

from homeassistant.helpers import entity_registry as er


async def test_imported_controller_gets_every_platform(hass, loaded_entry):
    # Given a controller whose configuration was imported once and stored locally.
    registry = er.async_get(hass)
    # When the integration has loaded from storage.
    entities = [
        entity
        for entity in registry.entities.values()
        if entity.unique_id.startswith("hub_")
    ]
    # Then every controller and zone entity is registered and available.
    assert {entity.unique_id for entity in entities} == {
        "hub_light",
        "hub_speed",
        "hub_now_playing",
        "hub_design",
        "hub_pattern",
        "hub_zone_front",
        "hub_zone_back",
    }
    assert all(
        hass.states.get(entity.entity_id).state != "unavailable" for entity in entities
    )
