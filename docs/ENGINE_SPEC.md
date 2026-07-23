# Grow Conductor — Engine Specification

This document is the **normative contract** for the pure core in
`custom_components/grow_conductor/core/`. Code and tests cite these rule
numbers. If code and spec disagree, one of them has a bug — fix whichever
is wrong, never silently drift.

The core never imports `homeassistant` (CI-enforced by ruff TID251 and
`tests/test_purity.py`). The adapter layer normalizes Home Assistant
entities into the input signals defined here and enforces the engine's
decisions on the physical switch.

## 0. Problem statement and vocabulary

A **grow light** must deliver up to `target_hours` of light per day to
plants that receive essentially no natural daylight. Because the light is
ugly, it may only run while **nobody can see it**. Subject to that hard
constraint, the engine maximizes delivered light and prefers **few, long
blocks** over many short ones (plants and humans both dislike flicker).

- **Viewer zones** — the places from which the light is visible
  (occupancy sensors for the room it is in and any room with sight lines).
- **Refuge zones** — places whose occupancy proves the occupants are
  settled *elsewhere* and cannot see the light (e.g. a home office on a
  work-from-home day).
- **Veto entities** — signals that force the light off regardless of
  occupancy detection (e.g. the TV is playing, so someone is almost
  certainly looking toward the light even if a sensor disagrees).
- **Trigger entities** — momentary movement signals at the boundary of
  the sleep area (e.g. the bedroom door contact). Only their
  *transitions* carry information; their level does not — an open door
  all day says nothing about who can currently see the light.
- **Plant day** — the scheduling period. It starts at the **anchor**
  time (default 22:00 local, the household's typical sleep boundary) and
  runs to the next anchor.
- **OBSERVED / UNOBSERVED** — the two visibility verdicts of §1. The
  light may only be lit while UNOBSERVED.

The engine is event-driven and deterministic: the adapter feeds it input
snapshots, light-state reports, and setting changes, each stamped with an
aware `datetime`; the engine returns a `Decision` (want the light on or
off, a display state, and the next time it must be re-evaluated even if
no input changes). The engine never reads clocks itself.

## 1. Visibility

Rule 1.1 (verdict). At any instant the household is either OBSERVED
(someone could see the light) or UNOBSERVED. The light may be commanded
on only while UNOBSERVED. The verdict is evaluated in the priority order
1.2 → 1.6; the first rule that applies wins.

Rule 1.2 (veto). If any veto entity is active, the verdict is OBSERVED.
Veto release has no extra hold: if a veto clears and no other rule makes
the household OBSERVED, the light may return immediately.

Rule 1.3 (viewer activity). If any viewer zone is active, or was last
active less than `clear_hold` ago (default 600 s), the verdict is
OBSERVED. The engine tracks the most recent viewer activity at all
times — including while asleep or away — so every transition into
UNOBSERVED implicitly waits out the hold. This single rule covers night
movement (waking up to visit the bathroom), the morning routine (moving
around before leaving), and "walked out the door but might step back in".
Exception: while the household is in confirmed refuge, rule 1.3c
applies instead.

Rule 1.3b (trigger pulses). Any state transition of a trigger entity
counts as **instantaneous** viewer activity: it stamps rule 1.3's
activity clock — cutting the light at once and starting the
`clear_hold` — but never sustains it. The *level* of a trigger entity
is never read: a door left open cannot block the schedule (contrast a
viewer zone, whose sustained activity keeps the household OBSERVED).
Transitions to or from unknown/unavailable are ignored, so a flapping
sensor cannot suppress lighting either.

Rule 1.3c (transient exposure during refuge). While the underlying
verdict is REFUGE (1.7), viewer evidence is tolerated briefly: viewer
activity flips the verdict to OBSERVED only once it has been
**continuously** active for `exposure_grace` (default 300 s); shorter
episodes — and trigger pulses (1.3b) — neither cut the light nor impose
a hold afterwards. An episode that does reach `exposure_grace` cuts at
that instant, and its falling edge imposes the normal `clear_hold`
before the light may return. Rationale (owner decision, DECISION.md
§9): a coffee run through a viewer room must not toggle a
work-from-home block. Only the refuge context is softened — while
asleep or away, every blip still cuts instantly per 1.3/1.3b.

Rule 1.4 (asleep). Otherwise, if the household is asleep, the verdict is
UNOBSERVED (reason `asleep`). This is the prime window.

Rule 1.5 (away). Otherwise, if nobody is home, the verdict is UNOBSERVED
(reason `away`).

Rule 1.6 (awake at home). Otherwise, someone is awake at home. The
verdict is UNOBSERVED (reason `refuge`) only if the refuge condition of
rule 1.7 holds; in every other case it is OBSERVED. There is no
weekend/weekday distinction and no "stay on after waking" latch: awake at
home without proof of refuge always means OBSERVED (see DECISION.md).

Rule 1.7 (refuge confirmation and hold). The refuge condition engages
when at least one refuge zone has been **continuously** active for
`refuge_confirm` (default 180 s); while unconfirmed, any gap resets the
confirmation clock. Once confirmed, refuge is **held** across gaps in
the evidence: it persists until no refuge zone has been active for
`refuge_hold` (default 600 s), so sensor decay during a coffee run does
not release it. A gap longer than `refuge_hold` releases refuge and a
later re-engagement must re-confirm from zero. If no refuge zones are
configured, the refuge condition never holds.

Rule 1.8 (fail-safe unknowns). Unknown inputs resolve toward OBSERVED:
an unknown sleep signal counts as awake; an unknown home signal counts
as home; an unknown refuge zone counts as inactive. Unknown viewer zones
and vetoes count as inactive (a dead sensor must not permanently veto
the schedule; the sleep/home gates above still protect the household —
this matches the legacy template behavior). The consequence is that a
total sensor outage starves the plants rather than exposing the light.

## 2. Photoperiod budget

Rule 2.1 (plant day). Delivered light is accounted per plant day. At
each anchor crossing the spent budget resets to zero. There is no
carry-over of deficit or surplus between plant days: a starved day is
accepted (fail-safe) and never causes compensation the household would
see.

Rule 2.2 (accrual from truth). The budget accrues from the **reported
physical light state**, not from the engine's commands. Time the switch
spends on — regardless of who turned it on (the engine, a wall button,
HomeKit) — counts toward `target_hours`. While the light state is
unknown, nothing accrues.

Rule 2.3 (cap). While spent ≥ `target_hours`, the engine wants the light
off (state `sated`) until the next anchor, regardless of visibility.

Rule 2.4 (open blocks split at the anchor). A block burning across the
anchor keeps burning (continuity is preferred); the portion before the
anchor is charged to the old day and the portion after it to the new day.

Rule 2.5 (minimum block). A **new** block may only start if the
remaining headroom is at least `min_block` (default 900 s); otherwise
the engine stays off (state `sated`, reason `low_headroom`). A block
already burning runs exactly to the cap. This prevents end-of-day
dribble without ever cutting a healthy block short.

## 3. Decisions, timing, and continuity

Rule 3.1 (decision). `want_on` is true iff: enabled (§4.3), UNOBSERVED
(§1), spent < target (2.3), and — when the light is currently off — the
minimum-block guard (2.5) passes.

Rule 3.2 (next review). Every decision carries `next_review`, the
earliest future instant at which the verdict could change with no input
event: the cap instant while burning, the `clear_hold` expiry while
waiting on viewer quiet, the `refuge_confirm` instant while a refuge is
confirming, and the next anchor otherwise. The adapter must re-evaluate
at `next_review`; between events and reviews the decision is stable.

Rule 3.3 (display state). The engine publishes exactly one of:
`lit` (with reason `asleep`/`away`/`refuge`), `observed` (with reason
`veto`/`viewers`/`awake_home`), `cooldown` (UNOBSERVED but waiting out
rule 1.3's hold — split from `observed` so the user can see the
countdown is working), `sated` (2.3 or 2.5, with reason
`target_reached`/`low_headroom`), or `standby` (disabled, §4.3).

## 4. Enforcement and manual control

Rule 4.1 (single writer). While enabled, the adapter reconciles the
physical switch to `want_on` — immediately on every decision change
**and** on every external flip of the switch. There is no manual
override while enabled; the escape hatch is rule 4.3.

Rule 4.2 (idempotence). The adapter only issues a command when the
reported state differs from `want_on`; the engine's decisions must be
stable under redundant reports (same light state twice, unchanged
snapshots).

Rule 4.3 (enabled switch). Each device has a restorable enabled switch.
While off: the engine issues no commands and reports state `standby`,
but keeps tracking visibility and accruing budget from reports (2.2), so
re-enabling is warm and manual light time is not double-delivered.

## 5. Persistence

Rule 5.1 (restore). Across a restart the adapter re-seeds the engine
with the persisted (plant-day start, spent seconds) pair. A seed whose
plant day differs from the current one is discarded — the ledger then
starts fresh at the current plant day's anchor (2.1 applies as if the
anchor were just crossed; mid-day restarts under-count at worst one
block, which fail-safes toward less light, never toward visible light).

Rule 5.2 (seeding inputs). On startup the engine treats input history as
empty: no viewer activity is remembered (a restart during sleep lights
up without waiting `clear_hold` — acceptable, the household is asleep),
and refuge confirmation starts from zero.

## 6. Tunables

| Tunable          | Default | Unit    | Meaning                                   |
| ---------------- | ------- | ------- | ----------------------------------------- |
| `target_hours`   | 12.0    | h/day   | Budget per plant day (number entity)      |
| `anchor`         | 22:00   | local   | Plant-day boundary (1.x windows pivot)    |
| `clear_hold`     | 600     | s       | Viewer quiet time before lighting (1.3)   |
| `refuge_confirm` | 180     | s       | Continuous refuge before lighting (1.7)   |
| `refuge_hold`    | 600     | s       | Confirmed refuge persists across gaps (1.7) |
| `exposure_grace` | 300     | s       | Viewer activity tolerated in refuge (1.3c) |
| `min_block`      | 900     | s       | Smallest headroom worth starting (2.5)    |

`target_hours` is a live number entity (0–20 h, step 0.5); the rest are
options-flow settings. `target_hours` is clamped to 20 so every plant
day keeps at least a 4-hour dark period (photoperiod hygiene).
