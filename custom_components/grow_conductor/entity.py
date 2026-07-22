"""Shared device info and dispatcher-driven entity base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

if TYPE_CHECKING:
    from .controller import GrowConductorController


def conductor_device_info(entry: ConfigEntry) -> DeviceInfo:
    """One device per grow light, named after the config entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Grow Conductor",
        model="Photoperiod scheduler",
        entry_type=DeviceEntryType.SERVICE,
    )


class ConductorEntity(Entity):
    """Base for conductor entities: dispatcher-driven, never polled."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, controller: GrowConductorController) -> None:
        self.controller = controller
        self._attr_device_info = conductor_device_info(controller.entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.controller.signal, self._on_controller_update)
        )

    @callback
    def _on_controller_update(self) -> None:
        self.async_write_ha_state()
