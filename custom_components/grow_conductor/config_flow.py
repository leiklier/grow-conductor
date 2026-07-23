"""Config and options flows.

One config entry per grow light. ``entry.data`` stays empty; every
setting lives in options (see const.py for the contract) so the options
flow can edit everything. The initial flow asks only for the light and
its visibility signals — timing tunables keep spec defaults and are
editable under Options → Timing.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONF_ANCHOR,
    CONF_CLEAR_HOLD,
    CONF_EXPOSURE_GRACE,
    CONF_HOME,
    CONF_LIGHT,
    CONF_MIN_BLOCK,
    CONF_REFUGE_CONFIRM,
    CONF_REFUGE_HOLD,
    CONF_REFUGES,
    CONF_SLEEP,
    CONF_TRIGGERS,
    CONF_VETOES,
    CONF_VIEWERS,
    DEFAULT_ANCHOR,
    DOMAIN,
)
from .core.tunables import Tunables

CONF_NAME = "name"

_LIGHT_SELECTOR = EntitySelector(EntitySelectorConfig(domain=["switch", "light", "input_boolean"]))
_BINARY_SELECTOR = EntitySelector(EntitySelectorConfig(domain=["binary_sensor", "input_boolean"]))
_HOME_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain=["zone", "person", "device_tracker", "binary_sensor", "input_boolean", "sensor"]
    )
)
_MULTI_OCCUPANCY_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=["binary_sensor", "input_boolean"], multiple=True)
)
_VETO_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain=["media_player", "binary_sensor", "switch", "input_boolean"], multiple=True
    )
)


def _signals_schema(defaults: dict[str, Any]) -> vol.Schema:
    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": defaults[key]} if defaults.get(key) else {}

    return vol.Schema(
        {
            vol.Optional(CONF_SLEEP, description=suggested(CONF_SLEEP)): _BINARY_SELECTOR,
            vol.Optional(CONF_HOME, description=suggested(CONF_HOME)): _HOME_SELECTOR,
            vol.Optional(
                CONF_VIEWERS, default=list(defaults.get(CONF_VIEWERS, []))
            ): _MULTI_OCCUPANCY_SELECTOR,
            vol.Optional(
                CONF_REFUGES, default=list(defaults.get(CONF_REFUGES, []))
            ): _MULTI_OCCUPANCY_SELECTOR,
            vol.Optional(CONF_VETOES, default=list(defaults.get(CONF_VETOES, []))): _VETO_SELECTOR,
            vol.Optional(
                CONF_TRIGGERS, default=list(defaults.get(CONF_TRIGGERS, []))
            ): _MULTI_OCCUPANCY_SELECTOR,
        }
    )


def _seconds_selector(max_value: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=max_value, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
        )
    )


def _timing_schema(defaults: dict[str, Any]) -> vol.Schema:
    tunables = Tunables()
    return vol.Schema(
        {
            vol.Required(
                CONF_ANCHOR, default=defaults.get(CONF_ANCHOR, DEFAULT_ANCHOR)
            ): TimeSelector(),
            vol.Required(
                CONF_CLEAR_HOLD, default=defaults.get(CONF_CLEAR_HOLD, tunables.clear_hold_s)
            ): _seconds_selector(7200),
            vol.Required(
                CONF_REFUGE_CONFIRM,
                default=defaults.get(CONF_REFUGE_CONFIRM, tunables.refuge_confirm_s),
            ): _seconds_selector(3600),
            vol.Required(
                CONF_REFUGE_HOLD,
                default=defaults.get(CONF_REFUGE_HOLD, tunables.refuge_hold_s),
            ): _seconds_selector(7200),
            vol.Required(
                CONF_EXPOSURE_GRACE,
                default=defaults.get(CONF_EXPOSURE_GRACE, tunables.exposure_grace_s),
            ): _seconds_selector(3600),
            vol.Required(
                CONF_MIN_BLOCK, default=defaults.get(CONF_MIN_BLOCK, tunables.min_block_s)
            ): _seconds_selector(7200),
        }
    )


class GrowConductorConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._name: str | None = None
        self._light: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_LIGHT])
            self._abort_if_unique_id_configured()
            self._name = user_input[CONF_NAME]
            self._light = user_input[CONF_LIGHT]
            return await self.async_step_signals()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_LIGHT): _LIGHT_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            assert self._name is not None and self._light is not None
            options = {CONF_LIGHT: self._light, **user_input}
            return self.async_create_entry(title=self._name, data={}, options=options)

        defaults = {CONF_HOME: "zone.home" if self.hass.states.get("zone.home") else None}
        return self.async_show_form(step_id="signals", data_schema=_signals_schema(defaults))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> GrowConductorOptionsFlow:
        return GrowConductorOptionsFlow()


class GrowConductorOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["signals", "timing"])

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                k: v
                for k, v in dict(self.config_entry.options).items()
                if k
                not in (
                    CONF_SLEEP,
                    CONF_HOME,
                    CONF_VIEWERS,
                    CONF_REFUGES,
                    CONF_VETOES,
                    CONF_TRIGGERS,
                )
            }
            options.update(user_input)
            return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="signals", data_schema=_signals_schema(dict(self.config_entry.options))
        )

    async def async_step_timing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**dict(self.config_entry.options), **user_input})
        return self.async_show_form(
            step_id="timing", data_schema=_timing_schema(dict(self.config_entry.options))
        )
