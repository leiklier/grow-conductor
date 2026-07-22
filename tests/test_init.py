"""Entry lifecycle: setup, entity inventory, unload, options reload."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grow_conductor.const import (
    CONF_ANCHOR,
    CONF_LIGHT,
    DOMAIN,
)


async def make_entry(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("switch.plantelys", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test plantelys",
        data={},
        options={CONF_LIGHT: "switch.plantelys"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_device_and_entities(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device({(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Test plantelys"

    entity_registry = er.async_get(hass)
    unique_ids = {
        e.unique_id.removeprefix(f"{entry.entry_id}_")
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    assert unique_ids == {"enabled", "target_hours", "state", "lit_today"}


async def test_unload_cleans_up(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_options_update_reloads(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    controller_before = hass.data[DOMAIN][entry.entry_id]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ANCHOR: "21:00:00"}
    )
    await hass.async_block_till_done()
    controller_after = hass.data[DOMAIN][entry.entry_id]
    assert controller_after is not controller_before
    assert controller_after.engine.tunables.anchor_minutes == 21 * 60


async def test_minimal_config_never_lights(hass: HomeAssistant) -> None:
    """No signals configured: rule 1.8 keeps the household OBSERVED forever."""
    entry = await make_entry(hass)
    controller = hass.data[DOMAIN][entry.entry_id]
    decision = controller.engine.decision
    assert decision is not None
    assert not decision.want_on
