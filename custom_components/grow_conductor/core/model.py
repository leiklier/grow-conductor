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
    MANUAL = "manual"
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
    # MANUAL (rule 4.4)
    MANUAL_OFF = "manual_off"
    MANUAL_ON = "manual_on"


# The rule-1.9 contexts are a subset of Reason: ASLEEP, AWAY, REFUGE, and
# AWAKE_HOME (everything else). Overrides are keyed to them (rule 4.4).
CONTEXTS = frozenset({Reason.ASLEEP, Reason.AWAY, Reason.REFUGE, Reason.AWAKE_HOME})


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
class Override:
    """A latched manual override (rule 4.4).

    ``on`` — the state the user flipped the light to.
    ``context`` — the rule-1.9 context it was latched in; a change
    releases the override.
    ``since`` — when it was latched (diagnostics only).
    """

    on: bool
    context: Reason
    since: datetime


@dataclass(frozen=True)
class Decision:
    """The engine's verdict, stable until an event or ``next_review`` (3.1, 3.2)."""

    want_on: bool
    state: LightState
    reason: Reason | None
    next_review: datetime | None
