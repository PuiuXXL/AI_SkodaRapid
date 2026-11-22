# Glare detection and lane-assist flag ("far lung din sens opus")

Status: **proposal, ready to implement** (2026-11-22). Owners: P1, P2, P3, P4 (one section each below).

## 1. What we build

When a strong light hits the driver's eyes (an oncoming car with high beams), the driver is blinded for a few
seconds. DriveMate detects it **deterministically in core** and raises a flag, `state.safety.glare.lane_assist`, that
the dashboard shows as "Asistență bandă activă". The flag goes off when the driver is back in control: light back to
normal, eyes open, gaze on the road.

**Detection = light + reaction.** P1 measures how bright the driver's face is; P2 compares it with the face's own
recent brightness (baseline) and requires the natural reaction to strong light (squinting, closing the eyes or looking
away) within one second. The decision is a fixed rule in core, never the LLM (plan principle 1).

**Demo.** A team member walks up to about 1 m from the driver and points a phone **flashlight** (torch mode, not the
photo flash) at the driver's face, held **level with the driver camera, right next to it** (not in front of the lens).
The driver squints. Within ~0.5 s the cockpit shows "Asistență bandă activă" and the event log "Orbire: lumină
puternică în ochi". Torch off, the driver opens the eyes and looks at the road: ~1 s later the flag goes off and the log
shows how long it lasted.

**Out of scope, say it clearly in the presentation.** DriveMate has no connection to the car (no CAN bus, no ADAS
interface). `lane_assist` is a state flag and a dashboard indicator: "this is the moment a car would turn lane keeping
on". No vehicle control.

## 2. Why these choices

| Choice | Reason |
|---|---|
| Torch, not the photo flash | A flash lasts a few ms: at 30 fps it is 0 or 1 frame, and a squint takes longer. The torch held 2-4 s gives a clear, sustained signal. |
| Torch next to the driver camera | The camera looks at the face; a light beside it lights the face, not the lens. Light into the lens washes out the frame, the face landmarks fail and the squint cannot be measured. |
| **Face** brightness, not the whole frame | The background (venue lights, windows) changes for other reasons; the face is what the light hits. |
| Baseline in core | All thresholds stay in `core/config/thresholds.yaml`, one place to tune (like `closed_ms` -> microsleep: P1 measures, P2 decides). |
| Light **and** reaction | Light alone also fires on a room light switched on; a reaction alone is a blink or fatigue. Together they are specific. |
| Fixed exposure on the driver camera | With auto exposure the camera darkens the image within < 1 s and the brightness jump disappears. The venue profile already exists in `perception/config/perception.yaml` (`auto_exposure: false`, `exposure_ms: 16`). |

## 3. Contract changes (P2 writes them first, everyone builds on them)

`shared/contracts.py`:

```python
class Light(ContractModel):
    """Driver-face brightness from the driver camera (P1). Measured on the face box only; null without a face."""

    face_luma: float | None = None       # mean grey level 0-255 inside the face box
    saturated_frac: float | None = None  # share of face-box pixels >= 250 (burnt by a strong light), 0..1
    frame_luma: float | None = None      # whole-frame mean, for the log / tuning only


class DriverPerception(ContractModel):
    ...
    light: Light = Field(default_factory=Light)  # P1 addition (glare)


class Glare(ContractModel):
    """Glare from an oncoming light (P2 rule, docs/glare-lane-assist.md). Style of Drowsiness."""

    active: bool = False
    lane_assist: bool = False             # the flag the dashboard shows; no vehicle control
    since: float | None = None
    baseline_luma: float | None = None    # core's rolling face baseline (for the dashboard / tuning)
    reason: str | None = None             # "light_and_reaction" / "strong_light"
    episodes: int = 0
    last_duration_ms: float | None = None


class Safety(ContractModel):
    ...
    glare: Glare = Field(default_factory=Glare)
```

New event-log types (core -> `/ws/ui`): `glare_start` (explanation, reason, face_luma, baseline), `glare_end`
(duration_ms, `end`: `recovered` / `timeout` / `reset`). New alert code: `glare` (level **P2**).

Update `tests/contract/make_fixtures.py` and the fixtures so a PerceptionFrame with `driver.light` validates.

## 4. The core rule (P2)

### 4.1 Thresholds (`core/config/thresholds.yaml`, new section; starting values, tune at rehearsal)

```yaml
glare:                          # docs/glare-lane-assist.md
  enabled: true                 # kill switch: false = the rule never fires
  min_speed_kmh: 0              # demo: 0 (the venue car is "moving" in the simulator); real road: 20
  baseline_s: 5.0               # rolling median of face_luma while not active
  baseline_min_frames: 30       # no baseline yet (start, face just found) -> never fires
  jump_abs: 45                  # bright = face_luma >= baseline + jump_abs ...
  saturated_frac_min: 0.15      # ... or this share of the face is burnt
  on_ms: 250                    # bright held this long ...
  reaction_window_ms: 1000      # ... and a reaction (SQUINT / CLOSED / gaze off the road) within this window
  allow_light_only: true        # demo safety net: a strong light alone also fires (see strong_*)
  strong_jump_abs: 80           # light-only path: face_luma >= baseline + this ...
  strong_saturated_frac: 0.25   # ... AND this share burnt (a room light does not burn the skin, a torch does)
  strong_on_ms: 1000            # ... held this long
  off_margin: 15                # light back to normal = face_luma <= baseline + off_margin
  recover_ms: 1000              # normal light + eyes OPEN (reliable) + gaze road (if calibrated) this long -> off
  max_active_s: 8.0             # still not back after this -> glare ends ("timeout"), the usual rules take over
  cooldown_s: 3.0               # no new episode right after one ends (no flicker)
  level: P2                     # arbiter level: silences voice and music, vetoes the LLM (C8)
  drowsiness_grace: true        # while active: no check-in / warn from a closure (the alarm stays, see 4.3)
  distraction_grace: true       # while active: gaze off the road is the glare reaction, not a distraction
```

### 4.2 State machine (`core/safety/glare.py`, `GlareRule`)

```
IDLE --(bright >= on_ms AND reaction within reaction_window_ms)----------------> ACTIVE  reason=light_and_reaction
IDLE --(allow_light_only AND strong light >= strong_on_ms)----------------------> ACTIVE  reason=strong_light
ACTIVE --(light normal AND eyes OPEN reliable AND gaze road, for recover_ms)----> IDLE    end=recovered
ACTIVE --(active > max_active_s)------------------------------------------------> IDLE    end=timeout
any --(reset)-------------------------------------------------------------------> IDLE    end=reset
```

* **bright** (per frame): `face_luma is not None and baseline is not None and
  (face_luma - baseline >= jump_abs or saturated_frac >= saturated_frac_min)`.
* **reaction** (per frame): `eyes.state in ("SQUINT", "CLOSED") or eyes.squint or
  gaze.zone not in ("road", "unknown")`.
* **baseline**: rolling median of `face_luma` over `baseline_s`, updated only while IDLE and not bright (a torch must
  not raise its own baseline). Frozen while ACTIVE. Cleared when the face is lost for more than 2 s.
* **gaze road** in recovery is required only when `gaze.calibrated` is true; otherwise eyes OPEN is enough.
* Speed below `min_speed_kmh`: the rule does nothing.
* On ACTIVE: `arbiter.raise_alert("glare", level, "glare", now)`, `state.safety.glare.active = lane_assist = True`,
  `log_event("glare_start", explanation=render("explanations", "glare", speed_kmh=...))`. No voice. Optional: one
  `visual_cue` (discrete signal), never a spoken sentence (the driver is blinded; talking adds load).
* On IDLE: `arbiter.clear("glare")`, flags off, `episodes += 1`, `last_duration_ms`, `log_event("glare_end", ...)`.

Wiring in `core/safety/__init__.py`: register `glare.on_frame` **before** `drowsiness.on_frame` (so the drowsiness
rule sees `glare.active` on the same frame) and call `glare.tick` with the other rules, before `arbiter.tick`.

### 4.3 Interactions with existing rules (must be handled, or the demo shows the wrong alert)

| Existing rule | Problem with the torch | What to do |
|---|---|---|
| P1 monitoring `mode_switch` (`perception/monitoring.py`: whole-frame luma jump >= 50 between two frames, held 1.5 s) | The torch switches on instantly: the jump can be read as a camera mode switch -> `monitoring_ok=false` -> "Nu te mai văd" | **P1**: a luma jump while the face is still tracked is not `mode_switch` (the colour <-> mono flip stays). See 5.1. |
| P2 drowsiness (`checkin_min_ms` 1000, `warn_ms` 2000, `alarm_ms` 3000) | A driver squeezing the eyes shut > 1 s gets "Facem o pauză?", > 2 s the warning | **P2**: with `drowsiness_grace`, while glare is active a closure does not trigger the check-in or the warning. **The alarm at `alarm_ms` stays**: eyes closed 3 s at speed is dangerous whatever the reason. Actor rule: squint, no closure longer than 2 s. |
| P2 distraction (off-road gaze, lap pattern) | Looking down / away from the light is the textbook reaction | **P2**: with `distraction_grace`, off-road gaze while glare is active (at most `max_active_s`) is not escalated. |
| Face lost (`face_lost_s` 2 s) | The driver shields the eyes with a hand -> no face | Actor rule: no hand in front of the face. The rule itself needs the face (face_luma null = no detection). |
| Assistant (P3) | Must not talk during glare | Automatic: level P2 vetoes the LLM and the arbiter stops voice and music. See 5.3. |
| SOS / microsleep alarm | Higher priority | Unchanged: P1/P0 outrank the P2 glare alert in the arbiter. |

## 5. Tasks per role

### 5.1 P1 - perception (~3-4 h)

1. **Face brightness per driver frame.** In the driver camera worker, where `MonitorModule` already computes
   `ImageStats` on the frame resized to `monitoring.analysis_width` (160 px): crop the grey frame to the face box
   (`perception/driver_cam/face.py: face_box_px`, scaled to the analysis width), compute `face_luma` (mean) and
   `saturated_frac` (share of pixels >= 250). No face -> both `None`. Cost: a few hundred pixels per frame.
2. **Send them.** `perception/frame_builder.py`: `frame["driver"]["light"] = {"face_luma", "saturated_frac",
   "frame_luma"}` (rounded to 0.1 / 0.001).
3. **Fix the `mode_switch` false positive.** `perception/monitoring.py`, `CameraMonitor.update`: the luma-jump branch
   (`abs(stats.luma - self._prev_luma) >= cfg.mode_switch_luma_delta`) must not fire while the face is detected on
   this frame. New config key in `perception.yaml` -> `monitoring`: `mode_switch_ignore_with_face: true`. The colour
   <-> mono flip is still a mode switch.
4. **Venue exposure.** Use the venue profile on the driver camera (`auto_exposure: false`, `exposure_ms: 16`). Check
   with the torch at 1 m, level with the camera, that the face is bright but not fully white (landmarks still found).
   If it burns out: lower `exposure_ms` (8-12) or use a lower torch level.
5. **Squint under strong light.** With `scripts/diag_eyes.py`, check that a squint into the torch reads `SQUINT` (or
   `squint=true`) and not `CLOSED`; tune `squint_ear_band` / `squint_veto` only if needed.
6. **Record** two sessions (torch episodes + controls, see section 7) with the existing recorder, for P2's replay
   tests and threshold tuning.
7. **Tests** (`tests/perception/`): synthetic frame with a brighter face box -> `face_luma` up, `saturated_frac` up;
   no face -> `None`; luma jump with a face -> no `mode_switch`; jump without a face -> `mode_switch` as before.
8. **Docs**: `docs/perception.md`, the new `driver.light` block and the `mode_switch` change.

**Done when:** `driver.light` arrives in core at frame rate, the torch at 1 m never gives `mode_switch`, and a squint
into the torch reads SQUINT.

### 5.2 P2 - core (~2-3 h)

1. **Contract** (section 3) first, and tell the team: P1 and P4 start from it.
2. **`core/safety/glare.py`**: `GlareRule(engine, arbiter)` with `on_frame`, `tick`, `reset`, the state machine of
   4.2, thresholds read with `th("glare", ...)`.
3. **Wiring** in `core/safety/__init__.py` (order of 4.2) and a reset listener.
4. **`thresholds.yaml`**: the `glare` section of 4.1. **`templates.yaml`**: `explanations.glare: "Lumină puternică în
   ochi la {speed_kmh} km/h. Asistență bandă activă."` (used in the event log and by `alert_explain`).
5. **Drowsiness grace** (`core/safety/drowsiness.py`, `_escalate` and the check-in scheduling): skip check-in and warn
   while `state.safety.glare.active` and `glare.drowsiness_grace`; the alarm branch unchanged.
6. **Distraction grace** (`core/safety/distraction.py`): no escalation of off-road gaze while glare is active.
7. **Fake perception** (`scripts/fake_perception.py`): key **`l`** ("lumină / far"): `face_luma` +90 over the normal
   value, `saturated_frac` 0.35, eyes `SQUINT` for 2.5 s, then back to normal. Lets P3 / P4 work without a camera and
   is the backup for the demo.
8. **Optional director test**: `UI_COMMANDS` += `"glare_test"` (core plays the same 2.5 s synthetic episode as key
   `l`), only for rehearsals; add it to `tests/contract/fixtures/dashboard_ui_messages.json`.
9. **Scorecard / trip report** (optional): `glare_episodes`, longest episode.
10. **Tests** `tests/core/test_glare.py` with `Rig`:
    * light + squint -> active within `on_ms`, alert `glare` at P2, `lane_assist` true, `glare_start` logged;
    * light without reaction, short -> nothing; strong light + saturation >= `strong_on_ms` -> active
      (`strong_light`); with `allow_light_only: false` -> nothing;
    * light back + eyes open + gaze road for `recover_ms` -> off, `glare_end` with `recovered`;
    * still squinting after `max_active_s` -> off with `timeout`;
    * during glare: a 1.5 s closure gives no check-in and no warning; a 3 s closure still gives the alarm;
    * off-road gaze during glare is not escalated;
    * no baseline yet (first second after the face appears) -> never fires; cooldown respected; reset clears.
11. **Docs**: `docs/core.md`, the rule and its thresholds.

**Done when:** key `l` in `fake_perception.py` lights the flag and turns it off, tests green, no drowsiness /
distraction alert during a 2.5 s squint.

### 5.3 P3 - assistant (~30 min)

1. **Silence**: nothing to build. The glare alert is at P2, so `safety.llm_allowed` is false and
   `assistant/policies.py` answers `stay_silent("safety_veto")`; core retries the skipped initiatives afterwards
   (`RETRY_REASONS`). Add a test in `tests/assistant/test_policies.py` (state with `safety.level="P2"`,
   `safety.alert="glare"` -> `safety_veto`, also for `driver_speech`).
2. **`alert_explain` for glare** ("De ce m-ai atenționat?"): the fixed text already uses core's explanation
   (`fallback.alert_explain`: "Te-am atenționat: {explanation}."). Add one line to `assistant/prompts/system.md` under
   `alert_explain`: for `glare`, say a strong light was in the driver's eyes and lane assist was on for those seconds.
3. **No spoken text during glare** (decision of section 4.2). Optional: a soft chime in
   `dashboard/public/sounds/` that P4's player can use for the `visual_cue`, if P2 emits one.
4. **Docs**: `docs/assistant.md`, one line in 3.5 (policies) about glare.

**Done when:** the assistant never speaks while `lane_assist` is on, and "de ce m-ai atenționat?" after an episode
gets the glare explanation.

### 5.4 P4 - dashboard (~1-2 h)

1. **Types** (`dashboard/src/types.ts`): `safety.glare` (section 3) and `driver.light`.
2. **Labels** (`dashboard/src/labels.ts`): `alerts.glare = "Orbire · asistență bandă"`; journal labels for
   `glare_start` ("Orbire: lumină puternică în ochi") and `glare_end` ("Revenit pe control după {s} s").
3. **Cockpit** (`dashboard/src/driver/Cockpit.tsx`, card "Siguranță"): while `safety.glare.lane_assist` is true, a
   clear indicator "Asistență bandă activă" (icon + accent colour + seconds since `glare.since`); when it ends, a
   short "Revenit pe control · {last_duration_ms} s" for a few seconds. Nothing to read while driving beyond the
   indicator.
4. **Dashboard** (`#/dashboard`, card "Privire" or "Sistem"): `driver.light.face_luma` against
   `safety.glare.baseline_luma` as a small live line, so the jury sees the jump (optional but good on stage).
5. **Control panel** (optional, if P2 adds `glare_test`): button "Testează orbirea" in "Siguranță și asistent".
6. **Presentation**: one slide (detection = light + reaction; no vehicle control) and the demo step.
7. **Tests** (`dashboard/tests/dashboard.test.tsx`): the indicator renders only with `lane_assist: true`; no value
   invented without data.

**Done when:** with key `l` in `fake_perception.py` the indicator appears and disappears, and the journal shows both
events.

## 6. Order and dependencies

1. P2: contract (30 min) -> tell the team.
2. In parallel: P1 (signal + `mode_switch`), P2 (rule + fake key `l`), P4 (indicator on fake data), P3 (test +
   prompt line).
3. Integration on the real camera at the venue: P1 + P2 tune `exposure_ms`, `jump_abs`, `saturated_frac_min`.
4. Rehearsal protocol (section 7), then freeze the thresholds.

## 7. Rehearsal protocol and acceptance

Same place, same light, same camera position as the demo. Driver camera on the venue profile.

**Torch trials (20):** torch at ~1 m, level with the driver camera and right next to it, on for 2-4 s; the driver
squints naturally (no hand in front of the face, no closure longer than 2 s), then looks back at the road.

**Controls (20):** normal blinks, a long blink, a mirror glance, a smile, looking at the passenger, the venue light
switched on and off, the torch pointed at the driver's chest (light near, not in the eyes).

**Acceptance:**

* torch trials: at least **19/20** detected; flag on **<= 0.5 s** after the torch is on (event-log timestamp against a
  phone video); flag off **<= 1.5 s** after torch off with eyes open;
* controls: **0** glare episodes;
* in all 40: no "monitorizare întreruptă", no check-in question, no drowsiness warning.

If the squint is often missed: keep `allow_light_only: true` (the strong light alone fires after 1 s). If the room
light causes false episodes: raise `strong_saturated_frac` / `saturated_frac_min`.

**Accuracy** is not known until this protocol is run: the light jump itself is easy to see with a fixed exposure; the
weak points are the squint measured on a very bright face and false positives from other light changes. Report the
measured numbers (detected / 20, false / 20, latencies) in `docs/eval/`.

## 8. Demo script (stage)

1. Trip running (scene 5 or a free drive), driver looking at the road, cockpit visible on the big screen.
2. Teammate steps in at ~1 m, torch on, held level with the driver camera beside it. Driver squints.
3. Cockpit: "Asistență bandă activă"; journal: "Orbire: lumină puternică în ochi". The assistant stays silent.
4. Torch off; driver opens the eyes, looks at the road. ~1 s: indicator off, "Revenit pe control după 2,8 s".
5. Optional: driver asks "Copilot, de ce m-ai atenționat?" -> the glare explanation.
6. Backup if the camera misbehaves: key `l` in `fake_perception.py` (or the "Testează orbirea" button).

## 9. Open decisions

| Decision | Who | Proposal |
|---|---|---|
| Level of the glare alert (P2 silences voice and music; P3 would not) | P2 | P2 |
| Drowsiness alarm during glare: unchanged at `alarm_ms`, or `+1 s` | P2 | unchanged (safety first) |
| A discrete chime at glare start, or nothing | P2 + P4 | one `visual_cue`, no voice |
| `glare_test` director command for rehearsals | P2 + P4 | yes, demo mode only |
| `min_speed_kmh` for the demo vs a real road | P2 | 0 at the venue, 20 on the road |
