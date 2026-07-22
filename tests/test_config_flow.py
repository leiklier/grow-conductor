"""Config and options flows: options contract, duplicate guard, editing."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grow_conductor.const import (
    CONF_ANCHOR,
    CONF_CLEAR_HOLD,
    CONF_HOME,
    CONF_LIGHT,
    CONF_MIN_BLOCK,
    CONF_REFUGE_CONFIRM,
    CONF_REFUGES,
    CONF_SLEEP,
    CONF_VETOES,
    CONF_VIEWERS,
    DOMAIN,
)


async def test_full_flow_creates_entry_with_options_contract(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form" and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Sofakrok plantelys", CONF_LIGHT: "switch.sofakrok_plantelys"},
    )
    assert result["type"] == "form" and result["step_id"] == "signals"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SLEEP: "binary_sensor.household_sleep_mode",
            CONF_HOME: "zone.home",
            CONF_VIEWERS: ["binary_sensor.sofakrok_occupancy"],
            CONF_REFUGES: ["binary_sensor.kontor_occupancy"],
            CONF_VETOES: ["media_player.sofakrok_tv"],
        },
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Sofakrok plantelys"
    assert result["data"] == {}  # house convention: everything in options
    assert result["options"] == {
        CONF_LIGHT: "switch.sofakrok_plantelys",
        CONF_SLEEP: "binary_sensor.household_sleep_mode",
        CONF_HOME: "zone.home",
        CONF_VIEWERS: ["binary_sensor.sofakrok_occupancy"],
        CONF_REFUGES: ["binary_sensor.kontor_occupancy"],
        CONF_VETOES: ["media_player.sofakrok_tv"],
    }


async def test_duplicate_light_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="switch.sofakrok_plantelys",
        options={CONF_LIGHT: "switch.sofakrok_plantelys"},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Duplicate", CONF_LIGHT: "switch.sofakrok_plantelys"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_options_flow_timing_preserves_signals(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sofakrok plantelys",
        options={
            CONF_LIGHT: "switch.sofakrok_plantelys",
            CONF_SLEEP: "binary_sensor.household_sleep_mode",
            CONF_VIEWERS: ["binary_sensor.sofakrok_occupancy"],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "timing"}
    )
    assert result["step_id"] == "timing"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ANCHOR: "21:30:00",
            CONF_CLEAR_HOLD: 300,
            CONF_REFUGE_CONFIRM: 120,
            CONF_MIN_BLOCK: 600,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_ANCHOR] == "21:30:00"
    assert result["data"][CONF_CLEAR_HOLD] == 300
    # Signals untouched by the timing step.
    assert result["data"][CONF_SLEEP] == "binary_sensor.household_sleep_mode"
    assert result["data"][CONF_VIEWERS] == ["binary_sensor.sofakrok_occupancy"]


async def test_options_flow_signals_can_clear_entities(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sofakrok plantelys",
        options={
            CONF_LIGHT: "switch.sofakrok_plantelys",
            CONF_SLEEP: "binary_sensor.household_sleep_mode",
            CONF_ANCHOR: "21:30:00",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "signals"}
    )
    # Submit without the sleep entity: it is cleared, timing survives.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_VIEWERS: [], CONF_REFUGES: [], CONF_VETOES: []}
    )
    assert result["type"] == "create_entry"
    assert CONF_SLEEP not in result["data"]
    assert result["data"][CONF_LIGHT] == "switch.sofakrok_plantelys"
    assert result["data"][CONF_ANCHOR] == "21:30:00"
