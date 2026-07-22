"""Visibility verdict (ENGINE_SPEC §1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import InputSnapshot, Reason
from .tunables import Tunables


@dataclass(frozen=True)
class Verdict:
    """Outcome of the §1 priority chain at one instant.

    ``reason`` is the lit-reason when ``may_light`` and the observed-reason
    otherwise. ``cooldown_until`` is set when the household is UNOBSERVED
    but rule 1.3's hold is still running; ``refuge_ready_at`` when rule
    1.7 is confirming — both are future instants the engine must review.
    """

    may_light: bool
    reason: Reason
    cooldown_until: datetime | None = None
    refuge_ready_at: datetime | None = None


def assess(
    snapshot: InputSnapshot,
    now: datetime,
    last_viewer_activity: datetime | None,
    refuge_since: datetime | None,
    tunables: Tunables,
) -> Verdict:
    """Evaluate rules 1.2-1.8 in priority order."""
    if snapshot.veto_active:  # 1.2
        return Verdict(False, Reason.VETO)
    if snapshot.viewer_active:  # 1.3, active half
        return Verdict(False, Reason.VIEWERS)

    # Underlying verdict, rules 1.4-1.7 (unknowns resolved per 1.8).
    refuge_ready_at: datetime | None = None
    if snapshot.asleep is True:  # 1.4
        underlying: Reason | None = Reason.ASLEEP
    elif snapshot.anyone_home is False:  # 1.5
        underlying = Reason.AWAY
    elif snapshot.refuge_active and refuge_since is not None:  # 1.6 + 1.7
        ready = refuge_since + timedelta(seconds=tunables.refuge_confirm_s)
        if now >= ready:
            underlying = Reason.REFUGE
        else:
            underlying = None
            refuge_ready_at = ready
    else:  # 1.6, no refuge evidence
        underlying = None

    if underlying is None:
        return Verdict(False, Reason.AWAKE_HOME, refuge_ready_at=refuge_ready_at)

    if last_viewer_activity is not None:  # 1.3, hold half
        hold_until = last_viewer_activity + timedelta(seconds=tunables.clear_hold_s)
        if now < hold_until:
            return Verdict(False, underlying, cooldown_until=hold_until)

    return Verdict(True, underlying)
