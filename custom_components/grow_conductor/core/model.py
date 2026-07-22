"""Value types shared across the core (ENGINE_SPEC §0, §3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LightState(StrEnum):
    """Display state (rule 3.3)."""

    LIT = "lit"
    OBSERVED = "observed"
    COOLDOWN = "cooldown"
    SATED = "sated"
    STANDBY = "standby"


class Reason(StrEnum):
    """Why the engine is in its display state (rule 3.3)."""

    # LIT
    ASLEEP = "asleep"
    AWAY = "away"
    REFUGE = "refuge"
    # OBSERVED
    VETO = "veto"
    VIEWERS = "viewers"
    AWAKE_HOME = "awake_home"
    # SATED
    TARGET_REACHED = "target_reached"
    LOW_HEADROOM = "low_headroom"


@dataclass(frozen=True)
class InputSnapshot:
    """Normalized input signals (ENGINE_SPEC §1).

    ``None`` means unknown; rule 1.8 defines the fail-safe resolution.
    Viewer/refuge/veto aggregation over entity lists happens in the
    adapter — the core only sees the OR.
    """

    asleep: bool | None = None
    anyone_home: bool | None = None
    viewer_active: bool = False
    refuge_active: bool = False
    veto_active: bool = False


@dataclass(frozen=True)
class Decision:
    """The engine's verdict, stable until an event or ``next_review`` (3.1, 3.2)."""

    want_on: bool
    state: LightState
    reason: Reason | None
    next_review: datetime | None
