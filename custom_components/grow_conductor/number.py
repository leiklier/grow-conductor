"""The target photoperiod knob (ENGINE_SPEC §6)."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .controller import GrowConductorController
from .core.tunables import MAX_TARGET_HOURS
from .entity import ConductorEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    controller: GrowConductorController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TargetHoursNumber(controller)])


class TargetHoursNumber(ConductorEntity, RestoreNumber):
    """Hours of light the plants should get per plant day."""

    _attr_translation_key = "target_hours"
    _attr_native_min_value = 0.0
    _attr_native_max_value = MAX_TARGET_HOURS
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.SLIDER

    def __init__(self, controller: GrowConductorController) -> None:
        super().__init__(controller)
        self._attr_unique_id = f"{controller.entry.entry_id}_target_hours"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_number_data()
        if data is not None and data.native_value is not None:
            self.controller.set_target(data.native_value)

    @property
    def native_value(self) -> float:
        return self.controller.engine.target_hours

    async def async_set_native_value(self, value: float) -> None:
        self.controller.set_target(value)
