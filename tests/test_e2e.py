"""End-to-end: real config entry, real input_boolean as the grow light.

Drives the integration through Home Assistant state changes and time and
asserts on the physical light, mirroring the core scenario tests at the
adapter level (single writer, rule 4.1).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.grow_conductor.const import (
    CONF_HOME,
    CONF_LIGHT,
    CONF_REFUGES,
    CONF_SLEEP,
    CONF_TRIGGERS,
    CONF_VETOES,
    CONF_VIEWERS,
    DOMAIN,
)

LIGHT = "input_boolean.plantelys"
SLEEP = "binary_sensor.sleep"
HOME = "zone.home"
VIEWER = "binary_sensor.stue"
REFUGE = "binary_sensor.kontor"
VETO = "media_player.tv"
DOOR = "binary_sensor.soverom_dor"

OPTIONS: dict[str, Any] = {
    CONF_LIGHT: LIGHT,
    CONF_SLEEP: SLEEP,
    CONF_HOME: HOME,
    CONF_VIEWERS: [VIEWER],
    CONF_REFUGES: [REFUGE],
    CONF_VETOES: [VETO],
    CONF_TRIGGERS: [DOOR],
}


def utc(hour: int, minute: int = 0, day: int = 5) -> str:
    return f"2026-01-{day:02d} {hour:02d}:{minute:02d}:00+00:00"


async def setup_conductor(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"plantelys": None}}
    )
    hass.states.async_set(SLEEP, "off")
    hass.states.async_set(HOME, "1")
    hass.states.async_set(VIEWER, "off")
    hass.states.async_set(REFUGE, "off")
    hass.states.async_set(VETO, "off")
    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()

    entry = MockConfigEntry(domain=DOMAIN, title="Stue plantelys", data={}, options=OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, suffix: str) -> str:
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")
    assert found is not None
    return found


def light_is_on(hass: HomeAssistant) -> bool:
    return hass.states.get(LIGHT).state == "on"


async def advance(hass: HomeAssistant, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_sleep_wake_and_night_movement(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    state_sensor = entity_id(hass, entry, "sensor", "state")

    # Awake at home: observed, light off.
    assert not light_is_on(hass)
    assert hass.states.get(state_sensor).state == "observed"

    # Sleep mode on: prime time (no viewer memory at startup, rule 5.2).
    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)
    assert hass.states.get(state_sensor).state == "lit"
    assert hass.states.get(state_sensor).attributes["reason"] == "asleep"

    # Night movement cuts immediately (rule 1.3).
    hass.states.async_set(VIEWER, "on")
    await hass.async_block_till_done()
    assert not light_is_on(hass)

    # Movement stops: cooldown, then relight after clear_hold (600 s).
    hass.states.async_set(VIEWER, "off")
    await hass.async_block_till_done()
    assert hass.states.get(state_sensor).state == "cooldown"
    assert not light_is_on(hass)
    await advance(hass, freezer, 601)
    assert light_is_on(hass)

    # Waking up cuts the light (morning routine is just OBSERVED).
    hass.states.async_set(SLEEP, "off")
    await hass.async_block_till_done()
    assert not light_is_on(hass)
    assert hass.states.get(state_sensor).attributes["reason"] == "awake_home"


async def test_veto_and_refuge(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    state_sensor = entity_id(hass, entry, "sensor", "state")

    # Work-from-home: office occupancy confirms after refuge_confirm (180 s).
    hass.states.async_set(REFUGE, "on")
    await hass.async_block_till_done()
    assert not light_is_on(hass)
    await advance(hass, freezer, 181)
    assert light_is_on(hass)
    assert hass.states.get(state_sensor).attributes["reason"] == "refuge"

    # TV starts playing: hard veto (rule 1.2).
    hass.states.async_set(VETO, "playing")
    await hass.async_block_till_done()
    assert not light_is_on(hass)
    assert hass.states.get(state_sensor).attributes["reason"] == "veto"

    # TV off again: immediate relight (no release hold).
    hass.states.async_set(VETO, "off")
    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()
    assert light_is_on(hass)


async def test_budget_cap_and_lit_today(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    target = entity_id(hass, entry, "number", "target_hours")
    lit_today = entity_id(hass, entry, "sensor", "lit_today")
    state_sensor = entity_id(hass, entry, "sensor", "state")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 1.0}, blocking=True
    )
    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)

    # One hour later the cap hits (rule 2.3): light off, sated.
    await advance(hass, freezer, 3601)
    assert not light_is_on(hass)
    assert hass.states.get(state_sensor).state == "sated"
    assert hass.states.get(state_sensor).attributes["reason"] == "target_reached"
    assert float(hass.states.get(lit_today).state) == 1.0

    # Next anchor (22:00 next day): budget resets, still asleep → relight.
    freezer.move_to(utc(22, 0, day=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert light_is_on(hass)
    assert float(hass.states.get(lit_today).state) == 0.0


async def test_manual_flip_is_reconciled(hass: HomeAssistant, freezer) -> None:
    """Rule 4.1: while enabled, an external flip is corrected immediately."""
    freezer.move_to(utc(22, 30))
    await setup_conductor(hass)
    assert not light_is_on(hass)

    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": LIGHT}, blocking=True)
    await hass.async_block_till_done()
    assert not light_is_on(hass)  # conductor turned it right back off


async def test_disabled_stops_commands_but_keeps_accounting(hass: HomeAssistant, freezer) -> None:
    """Rule 4.3: standby leaves the switch alone; manual light still accrues."""
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    enabled = entity_id(hass, entry, "switch", "enabled")
    lit_today = entity_id(hass, entry, "sensor", "lit_today")
    state_sensor = entity_id(hass, entry, "sensor", "state")

    await hass.services.async_call("switch", "turn_off", {"entity_id": enabled}, blocking=True)
    assert hass.states.get(state_sensor).state == "standby"

    # Sleep would normally light it — standby does not command.
    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert not light_is_on(hass)

    # Manual light for 30 minutes accrues budget (rule 2.2).
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": LIGHT}, blocking=True)
    await hass.async_block_till_done()  # let the report land before time jumps
    await advance(hass, freezer, 1800)
    assert light_is_on(hass)  # still untouched
    assert float(hass.states.get(lit_today).state) == 0.5


async def test_restore_across_reload(hass: HomeAssistant, freezer) -> None:
    """Rules 4.3 + 5.1: enabled flag, target and budget survive a reload."""
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    target = entity_id(hass, entry, "number", "target_hours")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 6.0}, blocking=True
    )
    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)
    await advance(hass, freezer, 7200)  # two hours of light delivered

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    controller = hass.data[DOMAIN][entry.entry_id]
    assert controller.engine.target_hours == 6.0
    # The two delivered hours survived the reload (rule 5.1).
    lit_today = entity_id(hass, entry, "sensor", "lit_today")
    assert float(hass.states.get(lit_today).state) == 2.0


async def test_door_trigger_cuts_but_open_door_never_blocks(hass: HomeAssistant, freezer) -> None:
    """Rule 1.3b end-to-end: transitions pulse, the level is ignored."""
    freezer.move_to(utc(22, 30))
    entry = await setup_conductor(hass)
    state_sensor = entity_id(hass, entry, "sensor", "state")

    hass.states.async_set(SLEEP, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)

    # Bedroom door opens at night: instant cut, before any occupancy fires.
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert not light_is_on(hass)
    assert hass.states.get(state_sensor).state == "cooldown"

    # The door STAYS open — after the hold the light returns anyway,
    # because a trigger's level is never read.
    await advance(hass, freezer, 601)
    assert light_is_on(hass)
    assert hass.states.get(state_sensor).state == "lit"

    # Unavailable flaps are not transitions: no pulse, no cut.
    hass.states.async_set(DOOR, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert light_is_on(hass)
    assert hass.states.get(state_sensor).state == "lit"
