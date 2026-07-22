"""Plant-day budget ledger (ENGINE_SPEC §2, §5)."""

from __future__ import annotations

from datetime import datetime, timedelta

from .tunables import Tunables


class PlantDayLedger:
    """Tracks delivered light per plant day, accruing from reported truth (2.2).

    All methods take aware ``datetime``s supplied by the caller; the
    ledger never reads clocks. Callers must feed time monotonically —
    the adapter guarantees this by stamping every event on arrival.
    """

    def __init__(self, tunables: Tunables) -> None:
        self._tunables = tunables
        self._day_start: datetime | None = None
        self._spent_s = 0.0
        self._lit_since: datetime | None = None

    # -- plant-day geometry -------------------------------------------------

    def anchor_before(self, now: datetime) -> datetime:
        """The most recent anchor at or before ``now`` (rule 2.1)."""
        minutes = self._tunables.anchor_minutes
        candidate = now.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
        if candidate > now:
            candidate -= timedelta(days=1)
        return candidate

    def next_anchor(self, now: datetime) -> datetime:
        return self.anchor_before(now) + timedelta(days=1)

    @property
    def day_start(self) -> datetime | None:
        return self._day_start

    @property
    def lit(self) -> bool:
        return self._lit_since is not None

    # -- accrual --------------------------------------------------------------

    def roll(self, now: datetime) -> None:
        """Advance to the plant day containing ``now``.

        Crossing an anchor charges the pre-anchor part of an open block to
        the old day and resets spent for the new one; the block itself
        keeps burning (rule 2.4).
        """
        current = self.anchor_before(now)
        if self._day_start is None:
            self._day_start = current
            return
        if current > self._day_start:
            if self._lit_since is not None:
                self._lit_since = max(self._lit_since, current)
            self._spent_s = 0.0
            self._day_start = current

    def light_reported(self, on: bool | None, now: datetime) -> None:
        """Fold a physical light-state report into the ledger (rule 2.2).

        ``None`` (unknown) closes any open block: nothing accrues while
        the light state is unknown.
        """
        self.roll(now)
        if on and self._lit_since is None:
            self._lit_since = now
        elif not on and self._lit_since is not None:
            self._spent_s += (now - self._lit_since).total_seconds()
            self._lit_since = None

    def spent_s(self, now: datetime) -> float:
        """Seconds delivered so far this plant day, including any open block."""
        self.roll(now)
        open_s = (now - self._lit_since).total_seconds() if self._lit_since is not None else 0.0
        return self._spent_s + open_s

    def headroom_s(self, now: datetime, target_s: float) -> float:
        return max(0.0, target_s - self.spent_s(now))

    def cap_instant(self, now: datetime, target_s: float) -> datetime:
        """The instant the budget runs out if the light burns from ``now`` on."""
        return now + timedelta(seconds=self.headroom_s(now, target_s))

    # -- persistence (rule 5.1) ------------------------------------------------

    def seed(self, day_start: datetime, spent_s: float, now: datetime) -> bool:
        """Adopt a persisted (day_start, spent) pair if it is still current.

        Returns True when adopted. A seed from a different plant day is
        discarded and the ledger starts fresh (rule 5.1).
        """
        if day_start != self.anchor_before(now):
            self.roll(now)
            return False
        self._day_start = day_start
        self._spent_s = max(0.0, spent_s)
        return True
