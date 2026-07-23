"""Typed view of the options contract (see const.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    CONF_ANCHOR,
    CONF_CLEAR_HOLD,
    CONF_HOME,
    CONF_LIGHT,
    CONF_MIN_BLOCK,
    CONF_REFUGE_CONFIRM,
    CONF_REFUGES,
    CONF_SLEEP,
    CONF_TRIGGERS,
    CONF_VETOES,
    CONF_VIEWERS,
    DEFAULT_ANCHOR,
)
from .core.tunables import Tunables


def _anchor_minutes(anchor: str) -> int:
    hours, minutes = anchor.split(":")[:2]
    return int(hours) * 60 + int(minutes)


@dataclass(frozen=True)
class Config:
    """Validated per-entry configuration."""

    light_entity: str
    sleep_entity: str | None = None
    home_entity: str | None = None
    viewer_entities: tuple[str, ...] = ()
    refuge_entities: tuple[str, ...] = ()
    veto_entities: tuple[str, ...] = ()
    trigger_entities: tuple[str, ...] = ()
    tunables: Tunables = field(default_factory=Tunables)

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> Config:
        return cls(
            light_entity=options[CONF_LIGHT],
            sleep_entity=options.get(CONF_SLEEP) or None,
            home_entity=options.get(CONF_HOME) or None,
            viewer_entities=tuple(options.get(CONF_VIEWERS, ())),
            refuge_entities=tuple(options.get(CONF_REFUGES, ())),
            veto_entities=tuple(options.get(CONF_VETOES, ())),
            trigger_entities=tuple(options.get(CONF_TRIGGERS, ())),
            tunables=Tunables(
                anchor_minutes=_anchor_minutes(options.get(CONF_ANCHOR, DEFAULT_ANCHOR)),
                clear_hold_s=float(options.get(CONF_CLEAR_HOLD, Tunables().clear_hold_s)),
                refuge_confirm_s=float(
                    options.get(CONF_REFUGE_CONFIRM, Tunables().refuge_confirm_s)
                ),
                min_block_s=float(options.get(CONF_MIN_BLOCK, Tunables().min_block_s)),
            ),
        )

    @property
    def input_entities(self) -> tuple[str, ...]:
        """Every entity that feeds the input snapshot (not the light itself).

        Trigger entities are deliberately absent: their level is never
        part of the snapshot (rule 1.3b) — the controller subscribes to
        their transitions separately.
        """
        singles = tuple(e for e in (self.sleep_entity, self.home_entity) if e)
        return singles + self.viewer_entities + self.refuge_entities + self.veto_entities
