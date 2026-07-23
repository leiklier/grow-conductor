"""Grow Conductor — photoperiod scheduling for grow lights nobody should see."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .config import Config
from .const import DOMAIN, PLATFORMS
from .controller import GrowConductorController


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = GrowConductorController(hass, entry, Config.from_options(dict(entry.options)))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller

    await controller.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Entity restores (enabled, target, budget seed) have been applied
    # during platform setup — enforcement may begin (rule 4.1).
    controller.arm()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        controller: GrowConductorController = hass.data[DOMAIN].pop(entry.entry_id)
        controller.async_stop()
    return unloaded
