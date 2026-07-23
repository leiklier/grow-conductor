"""Diagnostic sensors: scheduler state and delivered light.

Recorder discipline (house rule): both sensors gate their own writes —
the state sensor publishes only on a (state, reason) change and the
lit-hours sensor only when its 0.1 h quantized value or plant day
changes, so per-event dispatcher churn never becomes recorder rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .controller import GrowConductorController
from .core.model import LightState
from .entity import ConductorEntity

ATTR_REASON = "reason"
ATTR_SPENT_SECONDS = "spent_seconds"
ATTR_DAY_START = "day_start"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    controller: GrowConductorController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SchedulerStateSensor(controller), LitTodaySensor(controller)])


class SchedulerStateSensor(ConductorEntity, SensorEntity):
    """What the engine is doing and why (ENGINE_SPEC rule 3.3)."""

    _attr_translation_key = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [state.value for state in LightState]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: GrowConductorController) -> None:
        super().__init__(controller)
        self._attr_unique_id = f"{controller.entry.entry_id}_state"
        self._published: tuple[str | None, str | None] | None = None

    @property
    def native_value(self) -> str | None:
        decision = self.controller.engine.decision
        return decision.state.value if decision else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        decision = self.controller.engine.decision
        return {ATTR_REASON: decision.reason.value if decision and decision.reason else None}

    @callback
    def _on_controller_update(self) -> None:
        decision = self.controller.engine.decision
        current = (
            (decision.state.value, decision.reason.value if decision.reason else None)
            if decision
            else None
        )
        if current == self._published:
            return
        self._published = current
        self.async_write_ha_state()


class LitTodaySensor(ConductorEntity, SensorEntity, RestoreEntity):
    """Light delivered this plant day (rules 2.1/2.2), quantized to 0.1 h.

    Persists the exact ledger in attributes and re-seeds the engine on
    restore (rule 5.1). ``last_reset`` tracks the plant-day anchor so
    long-term statistics understand the daily reset.
    """

    _attr_translation_key = "lit_today"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 1

    def __init__(self, controller: GrowConductorController) -> None:
        super().__init__(controller)
        self._attr_unique_id = f"{controller.entry.entry_id}_lit_today"
        self._published: tuple[float, datetime] | None = None

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            day_start_raw = last.attributes.get(ATTR_DAY_START)
            spent_raw = last.attributes.get(ATTR_SPENT_SECONDS)
            day_start = dt_util.parse_datetime(day_start_raw) if day_start_raw else None
            if day_start is not None and spent_raw is not None:
                self.controller.seed_budget(day_start, float(spent_raw))
        await super().async_added_to_hass()

    def _current(self) -> tuple[float, datetime]:
        now = dt_util.now()
        spent = self.controller.engine.spent_s(now)
        return round(spent / 360.0) / 10.0, self.controller.engine.day_start(now)

    @property
    def native_value(self) -> float:
        return self._current()[0]

    @property
    def last_reset(self) -> datetime:
        return self._current()[1]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        now = dt_util.now()
        return {
            ATTR_SPENT_SECONDS: round(self.controller.engine.spent_s(now)),
            ATTR_DAY_START: self.controller.engine.day_start(now).isoformat(),
        }

    @callback
    def _on_controller_update(self) -> None:
        current = self._current()
        if current == self._published:
            return
        self._published = current
        self.async_write_ha_state()
