"""The per-light enabled switch (ENGINE_SPEC rule 4.3)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .controller import GrowConductorController
from .entity import ConductorEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    controller: GrowConductorController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EnabledSwitch(controller)])


class EnabledSwitch(ConductorEntity, SwitchEntity, RestoreEntity):
    """Engine enabled flag, restored across restarts.

    While off the engine issues no commands but keeps tracking visibility
    and budget (rule 4.3) — this is the manual-control escape hatch.
    """

    _attr_translation_key = "enabled"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: GrowConductorController) -> None:
        super().__init__(controller)
        self._attr_unique_id = f"{controller.entry.entry_id}_enabled"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, STATE_OFF):
            restored = last.state == STATE_ON
            if restored != self.controller.engine.enabled:
                self.controller.set_enabled(restored)

    @property
    def is_on(self) -> bool:
        return self.controller.engine.enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        self.controller.set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        self.controller.set_enabled(False)
