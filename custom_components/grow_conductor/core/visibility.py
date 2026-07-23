"""Visibility verdict (ENGINE_SPEC §1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import InputSnapshot, Reason
from .tunables import Tunables


@dataclass(frozen=True)
class ViewerMemory:
    """What the engine remembers about viewer activity (rules 1.3/1.3b/1.3c).

    ``active_since`` — start of the ongoing episode (None when quiet).
    ``last_end`` — falling edge of the most recent episode or pulse; the
    hold reference for the asleep/away contexts.
    ``sustained_end`` — falling edge of the most recent episode that
    reached ``exposure_grace``; the hold reference inside refuge (1.3c).
    """

    active_since: datetime | None = None
    last_end: datetime | None = None
    sustained_end: datetime | None = None


@dataclass(frozen=True)
class RefugeView:
    """The engine's rule-1.7 refuge status at one instant.

    ``engaged`` — confirmed and not lapsed (active or within refuge_hold).
    ``ready_at`` — set while an unconfirmed engagement is confirming.
    ``held_until`` — set while engaged on held (inactive) evidence: the
    instant the hold lapses if no refuge zone reactivates.
    """

    engaged: bool = False
    ready_at: datetime | None = None
    held_until: datetime | None = None


@dataclass(frozen=True)
class Verdict:
    """Outcome of the §1 priority chain at one instant.

    ``reason`` is the lit-reason when ``may_light`` and the observed-reason
    otherwise. ``cooldown_until`` is set when the household is UNOBSERVED
    but a clear-hold is still running. ``review_at`` is a future instant
    at which the verdict may flip with no input change (refuge
    confirmation, or a tolerated exposure reaching ``exposure_grace``).
    """

    may_light: bool
    reason: Reason
    cooldown_until: datetime | None = None
    review_at: datetime | None = None


def assess(
    snapshot: InputSnapshot,
    now: datetime,
    viewers: ViewerMemory,
    refuge: RefugeView,
    tunables: Tunables,
) -> Verdict:
    """Evaluate rules 1.2-1.8 in priority order."""
    if snapshot.veto_active:  # 1.2
        return Verdict(False, Reason.VETO)

    # Underlying context, rules 1.4-1.7 (unknowns resolved per 1.8).
    if snapshot.asleep is True:  # 1.4
        underlying: Reason | None = Reason.ASLEEP
    elif snapshot.anyone_home is False:  # 1.5
        underlying = Reason.AWAY
    elif refuge.engaged:  # 1.6 + 1.7
        underlying = Reason.REFUGE
    else:  # 1.6, no (confirmed) refuge evidence
        underlying = None

    if underlying is None:
        reason = Reason.VIEWERS if snapshot.viewer_active else Reason.AWAKE_HOME
        return Verdict(False, reason, review_at=refuge.ready_at)

    if underlying is Reason.REFUGE:
        return _assess_refuge(snapshot, now, viewers, refuge, tunables)

    # Asleep/away: every blip cuts instantly (1.3, 1.3b).
    if snapshot.viewer_active:
        return Verdict(False, Reason.VIEWERS)
    if viewers.last_end is not None:
        hold_until = viewers.last_end + timedelta(seconds=tunables.clear_hold_s)
        if now < hold_until:
            return Verdict(False, underlying, cooldown_until=hold_until)
    return Verdict(True, underlying)


def _assess_refuge(
    snapshot: InputSnapshot,
    now: datetime,
    viewers: ViewerMemory,
    refuge: RefugeView,
    tunables: Tunables,
) -> Verdict:
    """Rule 1.3c: transient exposure is tolerated during confirmed refuge."""
    reviews = [t for t in (refuge.held_until,) if t is not None]
    if snapshot.viewer_active and viewers.active_since is not None:
        exposed_at = viewers.active_since + timedelta(seconds=tunables.exposure_grace_s)
        if now >= exposed_at:
            return Verdict(False, Reason.VIEWERS)
        reviews.append(exposed_at)
        return Verdict(True, Reason.REFUGE, review_at=min(reviews))
    review_at = min(reviews) if reviews else None
    if viewers.sustained_end is not None:
        hold_until = viewers.sustained_end + timedelta(seconds=tunables.clear_hold_s)
        if now < hold_until:
            return Verdict(False, Reason.REFUGE, cooldown_until=hold_until, review_at=review_at)
    return Verdict(True, Reason.REFUGE, review_at=review_at)
