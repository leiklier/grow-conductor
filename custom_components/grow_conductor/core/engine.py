"""The event-driven scheduling engine (ENGINE_SPEC §1-§5).

The adapter feeds events stamped with aware datetimes; the engine never
reads clocks (deterministic and directly testable). Every mutation
returns the fresh :class:`Decision`; between events the decision is
stable until ``next_review`` (rule 3.2).
"""

from __future__ import annotations

from datetime import datetime

from .budget import PlantDayLedger
from .model import Decision, InputSnapshot, LightState, Reason
from .tunables import DEFAULT_TARGET_HOURS, Tunables, clamp_target_hours
from .visibility import Verdict, assess


class Engine:
    def __init__(
        self,
        tunables: Tunables | None = None,
        target_hours: float = DEFAULT_TARGET_HOURS,
    ) -> None:
        self._tunables = tunables or Tunables()
        self._target_s = clamp_target_hours(target_hours) * 3600.0
        self._ledger = PlantDayLedger(self._tunables)
        self._snapshot = InputSnapshot()
        self._last_viewer_activity: datetime | None = None
        self._refuge_since: datetime | None = None
        self._enabled = True
        self._light_on: bool | None = None
        self._decision: Decision | None = None

    # -- read surface ---------------------------------------------------------

    @property
    def tunables(self) -> Tunables:
        return self._tunables

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def target_hours(self) -> float:
        return self._target_s / 3600.0

    @property
    def snapshot(self) -> InputSnapshot:
        return self._snapshot

    @property
    def light_on(self) -> bool | None:
        return self._light_on

    @property
    def decision(self) -> Decision | None:
        """The most recent decision (None before the first event)."""
        return self._decision

    def spent_s(self, now: datetime) -> float:
        return self._ledger.spent_s(now)

    def day_start(self, now: datetime) -> datetime:
        self._ledger.roll(now)
        assert self._ledger.day_start is not None
        return self._ledger.day_start

    # -- events -----------------------------------------------------------------

    def handle_snapshot(self, snapshot: InputSnapshot, now: datetime) -> Decision:
        """Fold a normalized input snapshot into the engine."""
        previous = self._snapshot
        # Rule 1.3: remember viewer activity while it lasts and stamp its
        # falling edge, so the hold always counts from the end of activity.
        if snapshot.viewer_active or previous.viewer_active:
            self._last_viewer_activity = now
        # Rule 1.7: the confirmation clock starts on the rising edge only;
        # unrelated snapshot churn while active must not reset it.
        if snapshot.refuge_active and not previous.refuge_active:
            self._refuge_since = now
        elif not snapshot.refuge_active:
            self._refuge_since = None
        self._snapshot = snapshot
        return self._decide(now)

    def activity_pulse(self, now: datetime) -> Decision:
        """Instantaneous viewer activity from a trigger entity (rule 1.3b).

        Stamps rule 1.3's activity clock — cutting the light and starting
        the clear-hold — without sustaining activity; the trigger's level
        is never part of the snapshot.
        """
        self._last_viewer_activity = now
        return self._decide(now)

    def light_reported(self, on: bool | None, now: datetime) -> Decision:
        """Fold the physical light state into the ledger (rule 2.2)."""
        self._light_on = on
        self._ledger.light_reported(on, now)
        return self._decide(now)

    def set_target(self, hours: float, now: datetime) -> Decision:
        self._target_s = clamp_target_hours(hours) * 3600.0
        return self._decide(now)

    def set_enabled(self, enabled: bool, now: datetime) -> Decision:
        self._enabled = enabled
        return self._decide(now)

    def tick(self, now: datetime) -> Decision:
        """Re-evaluate with no input change (the ``next_review`` timer, 3.2)."""
        return self._decide(now)

    def seed_budget(self, day_start: datetime, spent_s: float, now: datetime) -> bool:
        """Adopt persisted budget state if still current (rule 5.1)."""
        return self._ledger.seed(day_start, spent_s, now)

    # -- decision (rule 3.1) ------------------------------------------------------

    def _decide(self, now: datetime) -> Decision:
        self._ledger.roll(now)
        verdict = assess(
            self._snapshot, now, self._last_viewer_activity, self._refuge_since, self._tunables
        )
        reviews = [self._ledger.next_anchor(now)]

        if not self._enabled:
            decision = Decision(False, LightState.STANDBY, None, min(reviews))
        elif not verdict.may_light:
            decision = self._decide_dark(verdict, reviews)
        else:
            decision = self._decide_light(verdict, now, reviews)

        self._decision = decision
        return decision

    def _decide_dark(self, verdict: Verdict, reviews: list[datetime]) -> Decision:
        if verdict.cooldown_until is not None:
            reviews.append(verdict.cooldown_until)
            return Decision(False, LightState.COOLDOWN, None, min(reviews))
        if verdict.refuge_ready_at is not None:
            reviews.append(verdict.refuge_ready_at)
        return Decision(False, LightState.OBSERVED, verdict.reason, min(reviews))

    def _decide_light(self, verdict: Verdict, now: datetime, reviews: list[datetime]) -> Decision:
        spent = self._ledger.spent_s(now)
        if spent >= self._target_s:  # rule 2.3
            return Decision(False, LightState.SATED, Reason.TARGET_REACHED, min(reviews))
        headroom = self._target_s - spent
        if self._light_on is not True and headroom < self._tunables.min_block_s:  # rule 2.5
            return Decision(False, LightState.SATED, Reason.LOW_HEADROOM, min(reviews))
        reviews.append(self._ledger.cap_instant(now, self._target_s))
        return Decision(True, LightState.LIT, verdict.reason, min(reviews))
