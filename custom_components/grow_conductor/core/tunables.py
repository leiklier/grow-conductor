"""Engine tunables (ENGINE_SPEC §6)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_TARGET_HOURS = 20.0  # keeps a >= 4 h dark period every plant day (§6)
DEFAULT_TARGET_HOURS = 12.0


@dataclass(frozen=True)
class Tunables:
    """Validated engine settings; adapter defaults live in const.py."""

    anchor_minutes: int = 22 * 60  # plant-day boundary, minutes after local midnight
    clear_hold_s: float = 600.0  # rule 1.3
    refuge_confirm_s: float = 180.0  # rule 1.7
    min_block_s: float = 900.0  # rule 2.5

    def __post_init__(self) -> None:
        if not 0 <= self.anchor_minutes < 24 * 60:
            raise ValueError(f"anchor_minutes out of range: {self.anchor_minutes}")
        for name in ("clear_hold_s", "refuge_confirm_s", "min_block_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


def clamp_target_hours(hours: float) -> float:
    """Clamp a requested daily target into the photoperiod-safe range (§6)."""
    return min(max(hours, 0.0), MAX_TARGET_HOURS)
