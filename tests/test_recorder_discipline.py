"""Recorder discipline: dispatcher churn must not become state writes.

House rule (learned the hard way in presence-conductor): every
state_changed event writes a recorder row, so entities may only publish
when their *published* value actually changes. This drives 24 rounds of
input churn through the controller and asserts zero writes anywhere.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.test_e2e import (
    REFUGE,
    SLEEP,
    entity_id,
    light_is_on,
    setup_conductor,
    utc,
)


async def test_no_writes_on_unrelated_churn(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)

    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)

    watched = [
        entity_id(hass, entry, "sensor", "lit_today"),
        entity_id(hass, entry, "sensor", "state"),
        entity_id(hass, entry, "switch", "enabled"),
        entity_id(hass, entry, "number", "target_hours"),
    ]
    before = {e: hass.states.get(e).last_updated for e in watched}

    # Refuge flapping while asleep: 24 snapshots, decision never changes
    # (rule 1.4 outranks refuge) — no entity may write a single row.
    for i in range(24):
        hass.states.async_set(REFUGE, "on" if i % 2 == 0 else "off")
        await hass.async_block_till_done()

    assert light_is_on(hass)
    for e in watched:
        assert hass.states.get(e).last_updated == before[e], f"{e} wrote during churn"
