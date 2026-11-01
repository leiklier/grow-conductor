# Architecture Decision Record

Decisions that shaped the engine, in the order they were made. Context:
this integration replaces two hand-grown template binary sensors
("Sofakrok/Spisebord Plantelys Required State"), two history_stats
helpers, two enforce-state automations, and the night-movement toggle
plumbing on the live instance.

## 1. Plant-day budget, not a rolling 24-hour window

The legacy system measured delivered light with a history_stats sensor
over a rolling 24 h window. A rolling window refills continuously, which
invites cap-flapping (at the cap, a minute of headroom trickles back
every minute) and makes "a day of light" hard to reason about. The
engine instead resets the budget at a fixed **anchor** (default 22:00 —
the same boundary the legacy away-schedule used). This is also closer to
what the plants experience: a photoperiod per day, followed by a dark
tail once the target is met. No carry-over between days: deficits are
accepted (fail-safe), never compensated where the household could see it.

## 2. One unified visibility model instead of weekday/weekend branches

Analysis of the legacy weekday template showed its `is_morning_routine`
and `arrival_cutoff` clauses were **redundant**: whenever the household
was awake and home, `should_be_on_by_schedule` was already false, so the
extra clauses never changed the outcome. The effective legacy semantics
were simply *(asleep ∧ no night movement ∧ no TV) ∨ nobody home*, capped
by the budget. The engine formalizes exactly that as §1 and drops the
workday/vacation inputs entirely — they only fed the redundant branches.

The legacy **weekend latch** (light stays on after waking, while someone
is home, until the cap) was deliberately dropped: the owner's stated
requirement is to never see the light, on any day. Weekend behavior now
equals weekday behavior.

## 3. Refuge zones instead of guessing "at work" from the workday sensor

The legacy system could not tell "away at work" from "working from
home"; the owner compensated by hand. Room-granular occupancy (Presence
Conductor) makes this solvable directly: if a refuge zone (home office)
is continuously occupied and no viewer zone is active, the light may run
while the household is awake at home. This replaces calendar heuristics
with observed reality — a sick day on the sofa keeps the light off, a
WFH day in the office lights the plants. Refuge requires *positive,
confirmed* evidence (rule 1.7); absence of viewer activity alone is
never enough while someone is awake at home, because uncovered rooms
(bathroom, hallway) would otherwise flicker the light every time the
occupant passes through them.

## 4. Greedy scheduling, no prediction

The engine lights whenever it may (§1) until the budget is spent. It
does not try to predict sleep or absence windows to place blocks
"optimally". Greedy naturally front-loads light into the sleep window
(one long block starting shortly after bedtime), matches the legacy
behavior the plants have thrived under, and keeps the core small and
fully deterministic. The continuity refinements are hysteresis, not
prediction: `clear_hold`, `refuge_confirm`, and `min_block`.

## 5. Fail-safe direction: unknown ⇒ observed ⇒ light off

Presence Conductor fails toward "someone is present" to avoid cutting
audio; Grow Conductor fails the same direction, which here means **light
off**. The worst case of a sensor outage is a starved plant day; the
worst case of the opposite default is an ugly purple glow during dinner.
Exception (rule 1.8): unknown viewer/veto entities count as inactive,
because the sleep/home gates already protect the household and a dead
motion sensor must not permanently disable the schedule — this matches
the legacy templates, where an unavailable occupancy sensor simply never
triggered night movement.

## 6. Budget accrues from the physical switch, not from commands

The lights are exposed to HomeKit and have wall access; the legacy
history_stats counted every source of on-time. Rule 2.2 keeps that
property: manual light is real light and consumes the day's budget.
Consequence: while the enabled switch is off, the ledger still runs.

## 7. Single writer while enabled

The legacy enforce-automation only reacted to template-state *changes*,
so a manual flip stuck until the next transition. The controller instead
reconciles on every external flip (rule 4.1). Manual experimentation is
what the enabled switch is for — mixing two writers on one switch is how
the old system got into silently-wrong states.

*Amended by §12:* manual flips are now honored as a context-scoped
override; the conductor still reverts its own stale echoes and never
fights itself.

## 8. Refuge continuity over absolute invisibility (2026-07-23)

Owner decision: on a work-from-home day, a coffee run through the
living room must not toggle the light — continuity of the block beats
absolute invisibility. Under the original rules every kitchen trip cost
~13 minutes of light (instant cut + `clear_hold` + refuge
re-confirmation, with the office sensor's decay releasing refuge on
top), several times a day: flicker for the human, starvation for the
plants. During **confirmed refuge only**, the engine therefore
tolerates transient viewer exposure (rule 1.3c, `exposure_grace`) and
holds refuge evidence across short gaps (rule 1.7, `refuge_hold`);
settling within sight of the light still cuts it once activity
sustains. The trade is explicit and accepted: brief glimpses of the
light while awake at home in refuge. Night movement, arrivals, and the
away context are untouched — every blip there still cuts instantly.

## 9. Core purity and testing conventions

Inherited unchanged from sonos-conductor and presence-conductor: pure
core (`core/` has zero `homeassistant` imports, enforced by ruff TID251
plus a poisoned-import test), event-driven engine with injected clocks,
adapter as a thin normalization + enforcement layer, uv tooling,
pytest-homeassistant-custom-component pinned to the production HA
version, and recorder discipline (no per-second entity churn; the
lit-hours sensor quantizes and rate-limits its publishes).

## 10. The bedroom door always cuts (2026-11-01)

Owner report: "it doesn't turn off when I open the door to soverom."
The live history showed two causes. The larger one was outside the
engine: the Zigbee coordinator stopped delivering messages from
2026-10-21 22:02 until Zigbee2MQTT restarted on 10-31 22:43. With Z2M
availability tracking disabled, the dead door contact kept showing a
plausible `off`, so no pulse ever arrived. The engine cause was rule
1.3c as first written. It ignored trigger pulses during confirmed
refuge, so on 10-31 at 23:04 the door opened while the light burned
for refuge and nothing happened. That exemption came from the
coffee-run argument (§8), but it does not fit triggers. The refuge
occupant's coffee run goes through viewer rooms. A bedroom-door
transition is someone crossing the sleep boundary. Rule 1.3b now cuts
in every context. §8's tolerance of short *viewer* episodes in refuge
is unchanged, with two tightenings found while replaying the live
history through the engine:

- A new short episode no longer bypasses a running hold. The old code
  checked "viewer active, still within grace" before the hold, so a
  second pass relit the light during the door's or a sustained
  episode's `clear_hold`.
- A tolerated episode keeps a burning block alive but never starts
  one. Light switching on in front of someone is the most visible
  thing the conductor can do.

In the 10-25..11-01 replay with the conductor left enabled throughout,
switch-ons fell from 48 to 32. Switch-ons while a viewer zone was
active fell from 13 to 0 (all 13 were refuge blocks on 11-01).

## 11. A paused media player is not a watcher (2026-11-01)

The original adapter counted `paused` and `idle` media players as
active vetoes. The live Apple TV reports `paused` for hours, sometimes
days, after the TV is switched off. Over ten days that added up to
4 days 1 h of `paused` with the screen dark, against 1.4 h with the
screen on. The stale veto blocked the whole 10-27→28 sleep window and
most of 10-28→29. `playing` is trustworthy: `playing` with the TV off
totalled 5 seconds. Rule 1.2b therefore keeps only `playing`,
`buffering`, and `on`. A household that pauses a show and wants that
covered should list the TV itself. A webOS/Android/Samsung TV reports
`on` while the screen is on, which is the signal that actually matters.

## 12. Manual override instead of strict single writer (2026-11-01)

§7 made the conductor revert every external flip, with the enabled
switch as the only escape hatch. In practice this was hostile. Between
10-25 and 11-01 the owner tapped the light off in Apple Home six times,
and each tap was reverted within about 260 ms. Every time, the owner
then switched the whole conductor off and lost the rest of the day's
schedule. The typical trigger was a morning when someone was up while
household sleep mode was still on. Each door or viewer cut lasted one
`clear_hold`, and then the light came back.

Rule 4.4 now honors a manual flip as an override that holds until the
*situation* changes (rule 1.9 context: wake, sleep, leave, arrive,
refuge on/off), until the user flips it back, or until the enabled
switch changes. This follows Light Conductor's override latch, which
the owner already lives with. There are two deliberate differences:

- **No timeout.** Context changes come several times a day. A timeout
  would only ever fire inside a context that keeps standing, and that
  is exactly when the user's choice should keep standing too.
- **Viewer and veto edges do not release.** In the morning case the
  next sofa sighting would otherwise release the latch, and the light
  would return `clear_hold` later, which is the bug itself.

Manual on gets the same treatment as manual off, so the switch obeys
Apple Home in both directions. Light delivered manually still counts
toward the day (§6). The adapter tells its own commands apart from
foreign flips using Home Assistant's context attribution, with a
direction-and-time fallback for late reports (rule 4.5). That is the
same distinction the logbook draws between "call_service" and
"HomeKit send command". For a long pause (guests sleeping on the
sofa), the enabled switch is still the right tool.
