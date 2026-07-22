# Grow Conductor

Photoperiod scheduling for grow lights **nobody should ever see** — a
Home Assistant custom integration.

Grow lights are great for plants and terrible to look at. Grow Conductor
delivers a configurable number of light hours per day, in blocks as long
and continuous as possible, scheduled exclusively into the moments when
no one can see the light: while the household sleeps, while nobody is
home, or while everyone is provably settled in a room without sight of
it (working from home in the office). Someone getting up at night,
walking through the room, or turning on the TV cuts the light instantly;
it quietly resumes once the coast has been clear for a while.

One config entry = one grow light = one device.

## How it works

The scheduler is a small deterministic engine (pure Python, no Home
Assistant imports, fully unit-tested) specified rule-by-rule in
[docs/ENGINE_SPEC.md](docs/ENGINE_SPEC.md); the reasoning behind the
design lives in [docs/DECISION.md](docs/DECISION.md). In short:

- **Plant day**: the daily budget (`target_hours`) resets at a fixed
  anchor time (default 22:00). No carry-over between days.
- **Visibility**: the light may run only while *unobserved* — asleep,
  away, or confirmed refuge (sustained occupancy in a room that cannot
  see the light). Viewer-room activity and hard vetoes (e.g. TV) force
  it off immediately; a quiet-time hold prevents flicker on the way back.
- **Fail-safe**: unknown sensors resolve toward "someone could see it".
  A sensor outage starves the plants a little; it never shows the light.
- **Truth-based accounting**: hours are counted from the physical switch
  state, so manual/HomeKit light counts toward the day's budget too.

### Entities per grow light

| Entity                 | Purpose                                                    |
| ---------------------- | ---------------------------------------------------------- |
| `number.…_target_hours`| The knob: hours of light per plant day (0–20, step 0.5)    |
| `switch.…_enabled`     | Off = standby: no commands, accounting continues            |
| `sensor.…_state`       | `lit` / `observed` / `cooldown` / `sated` / `standby`, with a `reason` attribute |
| `sensor.…_lit_today`   | Hours delivered this plant day (0.1 h resolution)           |

## Installation

1. HACS → Integrations → ⋮ → Custom repositories →
   `https://github.com/leiklier/grow-conductor` (category: Integration).
2. Install **Grow Conductor** and restart Home Assistant.
3. Settings → Devices & services → Add integration → Grow Conductor.

## Configuration

The flow asks for the light switch and the visibility signals:

- **Household asleep** — a binary sensor/toggle that is on while the
  household sleeps. This is the prime window.
- **Anyone home** — a zone (occupant count), person, tracker, or binary
  sensor. Away time is the second-best window.
- **Rooms with a view of the light** — occupancy sensors covering every
  spot the light is visible from. Any activity cuts the light and starts
  the quiet-time hold (night movement, morning routine — same rule).
- **Out-of-sight rooms** — occupancy for rooms that *cannot* see the
  light (home office). Sustained presence there allows daytime runs
  while you are awake at home — the work-from-home case.
- **Hard vetoes** — signals that force the light off regardless, e.g.
  the TV in the same room.

All signals are optional, but with none configured the fail-safe keeps
the light permanently off. Timing tunables (anchor, quiet-time hold,
refuge confirmation, minimum block) live under Options → Timing.

## Releases & channels

Same policy as [sonos-conductor](https://github.com/leiklier/sonos-conductor):
new behavior ships as a `vX.Y.Z-beta.N` pre-release first (HACS: enable
"Show beta versions"), soaks on a live install, then is promoted
unchanged to stable `vX.Y.Z`.

## Development

```sh
uv sync           # pinned to the production HA version
uv run pytest     # pure-core scenario tests + full HA e2e tests
uv run ruff check .
```

The `core/` package must never import `homeassistant` — enforced by
ruff (TID251) and a poisoned-import test. Code and tests cite the spec's
rule numbers; if behavior and spec disagree, one of them is a bug.
