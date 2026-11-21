# Perception (P1): technical decisions

> **Status: source of truth for P1.** Where this file disagrees with `roluri/P1-computer-vision.md` or with
> `DriveMate-PLAN-FINAL.md` §8, **this file wins**. Every difference is listed in
> [Differences from the role file](#differences-from-the-role-file), with the reason.
> The JSON contract (`shared/contracts.py`, owned by P2) still wins over both. Contract changes proposed here are
> listed in [§9 R4 visibility and proposed contract additions](#9-r4-visibility-and-proposed-contract-additions) and must be announced to the team first.

Perception turns the two cameras into a `PerceptionFrame` stream at 15 Hz. **P1 reports what it sees; what it means
(fatigue, risk, alarm) is decided by P2.** Organizer requirements are summarized in
[`hackathon-requirements.md`](hackathon-requirements.md).

---

## 1. Runtime

- **Python 3.11**, the same version for all four modules (as in plan §3), with a single shared `.venv`. The perception
  CI (`.github/workflows/perception.yml`) runs on 3.12 (P1 decision 2026-11-21): the code still targets 3.11 (ruff /
  mypy in pyproject), 3.12 checks it forward; `scripts/ci_local.ps1` runs the same steps locally.
  - MediaPipe does not ship reliable wheels for 3.13+, so 3.13/3.14 are out.
  - 3.12 would also work for perception, but core loads P3 and P4 code in the same process, and one interpreter
    version for the whole team avoids integration surprises. The speed difference does not matter here: the models do the heavy work.
- Environment, with [uv](https://docs.astral.sh/uv/):
  ```powershell
  uv python install 3.11
  uv venv --python 3.11 .venv
  .venv\Scripts\Activate.ps1            # Linux/macOS: source .venv/bin/activate
  uv pip install -r requirements/p1-perception.txt -r requirements/p1-dev.txt
  ```
- Config: `perception/config/perception.yaml`, validated by `perception/config.py` (Pydantic v2, unknown keys rejected).
  **No threshold lives in code.**

## 2. Process architecture

```
 ┌────────────────────────┐   ┌────────────────────────┐
 │ driver camera process  │   │ passenger camera proc. │   one OS process per camera
 │ capture → models →     │   │ capture → models →     │   (latest frame only, buffer 1)
 │ filters → features     │   │ filters → features     │
 └───────────┬────────────┘   └───────────┬────────────┘
             │  features + JPEG preview (queue, latest only)
             ▼                            ▼
 ┌──────────────────────────────────────────────────────┐
 │ main process (asyncio)                               │
 │  · merges both cameras → PerceptionFrame             │
 │  · WS client → ws://localhost:8000/ws/perception 15Hz│
 │  · receives commands: dialog_window, calibrate,      │
 │    debug, enroll                                     │
 │  · MJPEG server :8001 /video/driver, /video/passenger│
 └──────────────────────────────────────────────────────┘
```

**Why processes, not threads:**
- **GIL.** MediaPipe, ONNX Runtime and OpenCV release the GIL inside inference, but the Python glue code around them
  (landmark math, filters, kNN, JPEG encoding) does not. Two cameras plus asyncio networking in one interpreter
  compete for it, and the driver face would jitter.
- **Isolation.** If the passenger camera (DroidCam over USB) hangs or crashes a native library, the driver
  process keeps running. The plan requires exactly this ("if a camera drops, the other continues and the system
  announces it"). The main process sees the dead worker and sets `passenger.present=false`.
- **Degradation rule** (plan §8): if end-to-end p95 > 150 ms, lower the passenger rate first, then the YOLO rate.
  **The driver face is never degraded.**

Inside each camera process, capture runs in its own thread and keeps **only the latest frame**
(`CAP_PROP_BUFFERSIZE=1`, MJPG fourcc), stamped with `time.perf_counter()`
([`perception/capture.py`](../perception/capture.py), `LatestFrameCamera`):
- `wait_new(last_id, timeout)` never hands the same frame twice to a consumer;
- `dropped` counts frames replaced before anyone consumed them; `capture_fps` is measured over a 1 s window;
- the obtained format, size and fps are logged (and a warning when they differ from the request);
- after `max_read_failures` consecutive failed reads the camera is closed and reopened every `reconnect_s`;
- the source is behind a `FrameSource` interface: `OpenCVSource` (real camera) or `SyntheticSource` (tests, CI,
  `--synthetic`), so the capture logic is tested without a camera.
- **Backend:** from yaml; `auto` = `CAP_V4L2` on Linux, `CAP_DSHOW` on Windows (DSHOW honours MJPG + 720p;
  MSMF often ignores the FOURCC).
- **1080p30 capture, 720p processing** (2026-11-21): the C615 captures 1920x1080 MJPG at 30 fps; the models get ONE
  copy resized to `cameras.driver.process_width` (1280) per frame (`worker.downscale`; calibration and evaluation
  sessions use the same size, `perception/recorder.py`). Measured live with both cameras and a face: full 1080p
  processing 17.5 fps, 1600 px 26 fps (passenger degraded to 5 Hz), **1280 px 30 fps, passenger 10 Hz, e2e p95 64 ms**.
  The pixel thresholds stay the 720p-tuned ones: the driver must sit so the face is >= 250 px at 720p (R-FL3; at the
  first calibration the face was ~230 px and every `road` sample was rejected). The LifeCam is 720p in hardware.
- **Camera selection** (`capture.select_device`, at every open, 2026-11-21): (1) the `usb:<vid>:<pid>` selector,
  (2) `cameras.<cam>.device_name` (unique friendly-name substring: `C615`, `LifeCam`), (3) only with
  `cameras.dev_fallback: true` (default **false**) a device no enabled camera claims, the ones containing
  `cameras.fallback_name` (`Integrated`) first; the **driver has priority**, the passenger takes the fallback only when
  the driver does not need it. A fallback camera is logged as a warning and the frame says
  `monitoring_reason = "camera_fallback"`. An explicit index / path (`--device 0`) is used as is. The selection is
  deterministic, so `perception.main` prints at start a table of every device (index, name, VID:PID) and which camera
  gets it, exactly what the workers then open.

### 2.1 Camera controls (fixed exposure, focus, white balance, 50 Hz)

`cameras.<name>.controls` in yaml, applied by `scripts/camera_setup.sh` (Linux, `v4l2-ctl`; unsupported controls are
skipped with a message) or, on Windows, best-effort by `capture.py` through OpenCV properties.

| Control | Value | Why |
|---|---|---|
| `power_line_hz` | 50 | EU mains: removes 100 Hz flicker banding under venue LEDs / fluorescents (Linux only; OpenCV cannot set it on Windows). |
| `autofocus` | off | No focus hunting when the head moves; landmarks stay sharp. |
| `auto_exposure` | off, `exposure_ms` 16 | Auto-exposure "pumps" when the head turns or a hand passes, which changes EAR and landmark positions between frames. 16 ms is under the 33 ms frame period and limits motion blur. Needs our own lamp. |
| `auto_white_balance` | off, 4600 K | Stable colours for the detectors; tuned in the venue. |

**Two profiles.** *Laptop* (no lamp, current yaml): `auto_exposure: true`, `auto_white_balance: true`.
*Venue* (our lamp on the driver): manual exposure 16 ms, 4600 K, as in the table. **On Windows the camera driver
remembers the values we set, even after the app exits**: after a run with the venue profile, the webcam stayed at
16 ms everywhere and the image was nearly black without the lamp (mean luma 36/255; 120 after restoring auto). To
undo it, set the auto modes **explicitly to `true`** (`null` leaves the stored manual value in place). The overlay
shows the mean luma and warns `TOO DARK` below `monitoring.dark_luma`.

Lighting is the factor that hurts vision-based driver monitoring most (see the 100-Driver results in
[§11](#11-research-basis)), so we fix what we can at the camera instead of compensating later.

### 2.2 Runtime: workers, main process, commands (`perception/worker.py`, `perception/main.py`)

```powershell
python -m perception.main                          # enabled cameras -> ws://localhost:8000/ws/perception, MJPEG :8001
python -m perception.main --print --no-ws          # PerceptionFrame JSON lines on stdout (15 Hz), no core needed
python -m perception.main --synthetic --no-models  # no webcam, no model files (CI, quick checks)
python scripts/ws_sink.py --show --send debug      # stand-in for core's /ws/perception until P2's core exists
```

- **`CameraWorker`** (one spawn process per camera) owns the camera, the models and the detectors. Queues:
  `results` (maxsize 1, an unread older result is dropped), `jpegs` (maxsize 1), `commands`. Messages are plain
  dicts (`kind="frame"`, or a `kind="status"` heartbeat when no frame arrives).
- **Supervision:** a dead process, or one silent for `workers.stale_s` after its first frame (`workers.startup_s`
  before it: DSHOW opens 720p in ~4 s, the models load in ~2 s), is restarted with backoff 1, 2, 4 ... 10 s; the
  camera is `available = false` while it is down. Rates and debug are re-sent to the new process.
- **A missing camera is not a crash** (2026-11-21): the worker used to exit with code 2 when no first frame came in
  10 s, and the supervisor restarted it forever. Now the process stays up, sends a `camera_unavailable` heartbeat
  every 0.5 s (keeps the supervisor fed), logs `camera_unavailable` every `workers.unavailable_report_s` (5 s; open
  errors from the capture thread go to DEBUG, the worker reports them), keeps retrying the selection, and loads the
  models only when the first frame arrives. The frame reports the camera unavailable meanwhile.
- **Main process (asyncio):** polls the workers, merges the newest results into a `PerceptionFrame` every
  `1 / output.publish_hz` s (`perception/contract.py`), validates it, sends it to core, prints it with `--print`.
- **WebSocket:** reconnect with backoff (`ws_reconnect_s` doubling to `ws_reconnect_max_s`, +-20 % jitter); the
  outage is logged **once** until the next successful connection. Frames are "newest only"; acks have their own
  queue and are never dropped.
- **Commands from core** (`{"cmd": ...}` or `{"type": "<cmd>", ...}`), each answered with
  `{"type": "ack", "cmd", "status", "detail"}`:
  - `debug {on}`: full debug overlay in the MJPEG preview (landmarks, EAR, reference, head angles, fps, luma);
  - `dialog_window {open, to, until}`: turns the Gesture Recognizer on for that camera until `until` (6 s default);
    the head yes/no detector (AS8) plugs in here (step 4);
  - `calibrate {profile, quick}`: forwarded to the driver worker, which runs the gaze calibration (§3.4); ack
    `started`, one `calibration_prompt` per step, then ack `done` / `error`. The state rides on every worker frame,
    so a dropped result cannot lose the outcome.
  - `enroll {name}`: answered `not_implemented` until step 4.
- **MJPEG** `:8001/video/driver`, `/video/passenger` (`/` shows both, `/health` is JSON): the worker encodes the
  overlay JPEG (`output.video_width` px, `output.jpeg_quality`, `output.video_fps`) **only while a client is
  connected** (1.5 ms per JPEG measured).
- **Perf (plan J1):** per model and per stage p50 / p95 (`PerfTracker`), capture / process fps and dropped frames per
  camera, CPU / RAM of the process tree and GPU utilisation (`SystemMonitor`, pynvml when present), `e2e_ms_p95` =
  capture of the newest driver frame -> its publication.
- **Degradation** (`perception/degrade.py`): end-to-end p95 > `rates.degrade_e2e_p95_ms` -> halve the passenger face
  rate step by step (down to `degrade_min_passenger_face_hz`), then the YOLO rate (down to `degrade_min_phone_hz`);
  recover in reverse below `degrade_recover_ratio` x the limit; `degrade_hold_s` between steps. **The driver face is
  never degraded.**
- **Monitoring** (`perception/monitoring.py`, AS12 / AP5): `camera_unavailable`, `camera_frozen` (identical pixels
  for `frozen_frame_s`, checked on a sparse sample that keeps sensor noise: a static live scene differs by >= 1.3
  grey levels), `camera_covered` (no face for `face_lost_s` in a dark image), `face_lost`.
- Measured on the dev laptop (2026-11-21, dark room): 15.0 Hz published, e2e p95 55-82 ms, worker 4 ms per frame;
  the webcam itself dropped to 10 fps in the dark (auto exposure), 29.6 fps with normal light.

## 3. Detectors

### 3.1 Face: MediaPipe Face Landmarker
- **VIDEO running mode**, on the **full frame**, on CPU. Outputs: 478 landmarks (iris 468–477), 52 blendshapes,
  facial transformation matrix.
- **No manual crop.** In VIDEO mode MediaPipe already tracks the face between frames and runs the detector only
  when tracking is lost. A hand-made crop adds code, can cut off the face during fast head turns, and gains little.
- Driver camera: every frame (target ≥ 20 fps, ≤ 15 ms). Passenger camera: 10 Hz.

### Face Landmarker rules (R-FL1 – R-FL5)

| Rule | What | Where |
|---|---|---|
| **R-FL1** | `num_faces = 1` on each camera. MediaPipe's internal tracking/smoothing between frames only works with a single face. Each camera sees one person by design. | `face.num_faces` (fixed to 1 by validation) |
| **R-FL2** | The three confidence thresholds live in yaml: detection 0.5, presence 0.5, tracking 0.6 (starting values). | `face.min_detection_conf`, `face.min_presence_conf`, `face.min_tracking_conf` |
| **R-FL3** | The face must be **≥ ~250 px wide** in the frame. Below that, eye landmarks are too coarse for EAR: the frame is flagged `face_too_small` and the face confidence is reduced (`width / min_face_width_px`). | `face.min_face_width_px`; `FeatureFrame.face.too_small`, `.conf` |
| **R-FL4** | **Lids lowered but not meeting = squinting, not closed.** Squinting (sun, smiling, concentrating) lowers EAR without the lids meeting; it must not count in PERCLOS or `closed_ms`. Squint if `EAR / reference` lies inside `squint_ear_band` **and `eyeBlink` < `blendshape_closed`**; a fast fall that settles there for longer than `plateau_check_ms` is cancelled. *Revised 2026-11-21:* `eyeSquint` is not used, it is person-dependent (0.49 at rest in the diag session) and just as high with the eyes squeezed shut (0.71). | `eyes.squint_ear_band`, `eyes.blendshape_closed`, `eyes.plateau_check_ms` |
| **R-FL5** | Face Landmarker **does not identify people**: identity is YuNet + SFace only (§3.7). `brow*` blendshapes are optional signals at most, never used for identity or safety decisions. | — |

Face Landmarker exposes **no per-face confidence score** in the Tasks API (landmark `presence` / `visibility` are
`None`), so `FeatureFrame.face.conf` is geometry-based: 1.0 for a face at or above `min_face_width_px`, scaled down
linearly below it, 0 when no face is found.

Measured on the dev laptop webcam (1280×720, normal sitting distance): the face is only **~165 px** wide, below
R-FL3. For the demo, the driver camera must be closer to the face (or have a narrower field of view).

### 3.2 Eyes: EAR, local reference, blink shape
Rewritten 2026-11-21 after a diagnostic on a labelled live session (`scripts/diag_eyes.py`, numbers below). The
old design (one global baseline from the first 10 s, Median3, hysteresis 0.65 / 0.80) failed for two reasons that
had nothing to do with filtering: **(1)** the open-eye EAR drifts with head pitch (0.30 at the start, 0.24 a minute
later with the head 7-10 deg lower), so open eyes read as ratio ~0.78 < `k_open` and the hysteresis stayed CLOSED for
up to 13 s (14 of 18 false closures had the eyes open); **(2)** looking down lowers the lids as much as a closure.
Blinks themselves were sharp: 180 ms at 50 % depth in the raw EAR, 192 ms after Median3.

- **EAR on each eye** in **pixels** (right `33,160,158,133,153,144`; left `362,385,387,263,373,380`) and the
  `eyeBlink`, `eyeLookDown` blendshapes. An eye is unreliable if narrower than `min_eye_width_px` or than
  `unilateral_width_ratio` x the other eye (head turned, foreshortened).
- **Reference per eye** (`EarReference`): p90 of the EAR over the last `local_ref_window_s` (4 s), floored at
  `ref_floor_ratio` (0.6) x the global reference (calibration, or provisional p90 of the first 10 s).
  - **All frames** go into the window: blinks are < 10 % of the frames, so the p90 is the open level. Excluding
    "closed" frames deadlocks: a closure started on a too-high reference freezes the reference and never ends.
  - The floor keeps a closure longer than the window closed (a closed eye reads ~0.5-0.6 of the floor).
  - `get(side, zone)` takes a gaze zone: the per-zone reference of the gaze calibration (phase 5) plugs in there.
- **Bilateral rule:** the eye signal r is the MAX of EAR / reference over the reliable eyes: "closed" needs both eyes
  (one eye only when the other is unreliable). A wink or a one-eye landmark glitch is not a closure.
- **Gaze conditioning:** head pitch <= -`pitch_down_deg` (15) or >= `pitch_up_deg` (20), or `eyeLookDown` >=
  `look_down_threshold` on the **last open frame** -> threshold `drop_ratio_relaxed` (0.45) instead of `drop_ratio`.
  `eyeLookDown` is read before the fall because it rises during every blink (the lids cover the iris).
  **No closure may start while the head moves** (> `head_motion_deg` in `head_motion_window_s`), and one that
  started is cancelled if the head starts moving within that window: the eyes lead the head in a gaze shift.
- **Shape, not a level:**
  - **fast fall**: from the last frame above `drop_ratio + min_fall_depth` to below the threshold in <=
    `fall_max_ms` (150) -> blink or closure. `min_state_frames` (2) frames below confirm `CLOSED`, but `closed_ms`
    counts from the interpolated drop, not from the confirmation;
  - **slow fall** (drowsy lids) counts only deep (`slow_close_ratio` 0.47) with the lids meeting
    (`eyeBlink` >= `blendshape_closed` 0.45, or >= `blendshape_strong` 0.65 alone), never while relaxed;
  - **end, two tiers** (2026-11-21): r back above half the depth of the episode (the same 50 % rule as the
    duration). A closure still within `blink_max_ms` (400) ends at the **first** open frame and counts as a blink
    (two blinks 250 ms apart stay two blinks); a longer one ends only after `reopen_min_frames` (2) open frames
    **in a row**, so one bright frame no longer restarts `closed_ms` from 0; the duration spans the first down to the
    last up crossing. `driver.eyes.blink_count` (monotonic) lets a 15 Hz consumer count every blink;
  - **gaps** (long closures only): frames without a face / with unreliable eyes inside a confirmed closure keep it going for up to
    `closure_gap_max_ms` (200): state `CLOSED`, `closed_ms` counting and `reliable` held (P2's microsleep rule reads
    `eyes.reliable and closed_ms`); a longer gap ends it as an event at its last valid frame;
  - **plateau check** (from `plateau_check_ms`, 300): the episode stays closed only while the lids look closed
    (r < squint band low and `eyeBlink` >= `blendshape_closed`, or `eyeBlink` >= `blendshape_strong`); otherwise
    it was a fast squint (cancelled, no event) or a closure that opened into a squint (ends there).
- **Duration = time below 50 % of the depth**, interpolated between frames (`perception/eye_signal.py`); <=
  `blink_max_ms` = blink, longer = closure (`long_closure` while it lasts). Each event also carries `min_ratio`,
  `reopen_ms` (minimum -> 50 % on the way up, Schleicher et al. 2008) and `close_speed` (depth / s).
- **PERCLOS P80** (Wierwille / Dinges, FHWA 1998): share of the last 60 s with closure >= 80 %, closure =
  (1 - r) / (1 - closed level); the closed level is the median minimum of the last 10 blinks
  (`closed_level_default` before that). Separate from the blink threshold: half-closed lids do not count.
- **Outputs:** `ear`, `eye_used`, `blink_ms`, `closed_ms`, `perclos_60s` (P80), `reliable`, `state`, `squint`,
  `long_closure`, `relaxed`, `ratio`, `ratio_left/right`, `ref_left/right` (see §9).
  - **P1 reports `closed_ms`. The microsleep threshold belongs to P2.**
  - `reliable=false` (sunglasses, eyes not visible) -> only head metrics are trusted.
- **Tuned on one session** (laptop webcam, 1280x720 YUY2 at 29.6 fps, face ~285 px): `drop_ratio` 0.70 (0.65
  missed shallow blinks, 0.75 added false closures), `slow_close_ratio` 0.47 (2 s closures 0.42-0.47, a hard squint
  0.48-0.51). Re-check both on every new camera / person with `scripts/diag_eyes.py`.

| Replay of `20261121-022040_eval-cristian-before` | old detector | new detector |
|---|---|---|
| cued blinks detected | 9/10 (90 %), median 192 ms | **10/10, median 167 ms** |
| false closures | 18 (4.7/min) | **1 (0.26/min)** (a 1.7 s look at the lap at -27 deg) |
| squint / smile reported closed | 7 | **0** |
| closed_ms vs the raw signal (2 labelled closures) | 1617 vs 1603, 1312 vs 1304 ms | 1586 vs 1603, 1277 vs 1308 ms |

The `closed_ms` error against the **instruction window** (568-601 ms) is a labelling artefact: the closures started
0.5-0.8 s after the prompt and lasted 1.3-1.6 s, not 2 s. The guided protocol now labels closures with SPACE (press
when closing, press when opening).

**Held-out live session** `20261121-025703_eval-cristian-after` (new protocol, thresholds NOT tuned on it):
- blinks: 8/10 by the eval rule; of the 2 misses, one was a blink made 1.2 s after the cue (detected, outside the
  1.0 s match window) and one cue was not followed by a blink (ratio never below 0.83);
- 2 s closures: no SPACE label was recorded (window focus), so the 4 real closures count as "false" in the report;
  against the raw signal, `closed_ms` was 2524 / 2104 / 822 / 2483 ms vs 2654 / 2197 / 1007 / 2432 ms (51-185 ms);
- **open problem: hard squints.** 3 labelled squints went down to ratio 0.30-0.42 with eyeBlink 0.51-0.55, the same
  as a closure (0.28-0.45, 0.52-0.65). EAR + blendshapes cannot separate them at this resolution; the upgrade path is
  an eye-crop CNN (§11, Ersoy et al., 99.1 % eye state);
- 1 look at the lap at pitch -34 deg for 3.5 s read as closed (ratio 0.28, eyeBlink 0.57): with the head that low the
  lids cover the eye; a stricter rule below ~-25 deg is a candidate, to be decided on a third session;
- head: jitter 0.006 / 0.007 / 0.028 deg, signs correct (yaw +31, pitch +32, roll +25 / -40); speaking 5/5 segments,
  0.44 s median latency.

**Eye-state CNN** (`perception/driver_cam/eye_cnn.py`, `eyes.cnn`), the answer to the hard squint above:
**open-closed-eye-0001** (Intel Open Model Zoo, Apache-2.0, MRL Eye Dataset, 95.8 %, 0.0014 GFLOPs) on a square crop
of each eye (1.6 x the corner distance, 32x32 BGR), on every driver frame when the model file exists. Output:
`face.eye_closed_p` = p(closed) per eye in the FeatureFrame (recorded from now on) and `eyes.cnn_closed` = the most
open reliable eye (bilateral, like the EAR). Fusion, only where EAR is ambiguous:
- p(closed) < `cnn.open_max` (0.30): **veto**: a plateau past `plateau_check_ms` is a squint, no slow closure starts,
  and the "very low ratio" clause no longer holds the closure (3 consecutive open frames end it);
- p(closed) >= `cnn.closed_min` (0.70): **confirms** a plateau in the squint band (people whose EAR barely drops);
- fast blinks never wait for the CNN.

**Not validated yet:** recordings hold no pixels, so the CNN cannot be replayed on the 2026-11-21 sessions; the
thresholds are softmax defaults and must be checked on a live session (squint, smile, closures). If the CNN reads
closed eyes as open in the venue light, set `eyes.cnn.enabled: false` (safety: a wrong veto shortens a closure).

### Diagnostics and evaluation tools
- `scripts/eval_eyes.py --name <n>`: guided live protocol (~4 min) -> labelled session in `data/features/` + report
  in `docs/eval/`; `--session <dir>`: re-evaluate a recorded session; `--ab-num-faces`: R-FL1 A/B (two Face
  Landmarkers on the same frames). Result 2026-11-21: blink width 165 vs 160 ms (num_faces 1 vs 2), no reason to
  change R-FL1.
- `scripts/diag_eyes.py --session <dir>`: plots and tables in `data/diag/<session>/` (local): raw EAR per eye,
  detector input, blendshapes, pitch, labels, states; one panel per cued blink, closure, false closure, squint,
  look-down; the real frame rate.
- `scripts/tune_one_euro.py --session <dir>`: per-axis One Euro grid (§3.3).

### 3.3 Head angles and slow events
- Yaw / pitch / roll from the transformation matrix (Euler ZYX, R = Rz(roll) Ry(yaw) Rx(pitch)), smoothed with a
  **One Euro filter per axis** (`filters.one_euro_head`): little lag on fast movements (mirror checks, nods),
  strong smoothing when the head is still (`perception/driver_cam/head.py`).
  - **Tuning** (`scripts/tune_one_euro.py`, Casiez et al. 2012): lowest frame-to-frame jitter on neutral still frames
    with a lag <= 50 ms on fast head movements. Raw jitter yaw 0.10 / pitch 0.14 / roll 0.18 deg -> filtered
    0.03 / 0.06 / 0.15 deg (`docs/eval/one-euro-2026-11-21.md`).
  - **Jitter metric:** std of consecutive differences / sqrt(2), on neutral frames (eyes open, not speaking, not
    yawning). The old metric (plain std over the "still" window, 2.2 deg pitch / 3.8 deg roll) measured the real slow
    drift of a head that is never perfectly still: raw and filtered were equal, so no filter could fix it.
  - **Plausibility:** |yaw| > 70, |pitch| > 50 or |roll| > 45 deg -> angles reported as unknown and the filters
    restart. A near-profile face gives garbage fits (roll 80 deg while the head was turned +50 deg left).
- **Axis signs, in the driver's terms:** `yaw > 0` = head turned to the driver's **left** (left mirror);
  `pitch > 0` = head **up**; `roll > 0` = head tilted to the **left shoulder**. MediaPipe's pose is in camera space
  (x = image right, y = up, z = towards the camera, image not mirrored); `AXIS_SIGNS` maps the raw rotations about
  x / y / z to this convention. Unit tests use known rotation matrices; the guided eval (`scripts/eval_eyes.py`,
  "turn left / up / tilt left / tilt right", 5 s each, the first 2 s skipped for the reaction time) checks the
  signs live and reports `pose_*_sign_ok`. **Verified 2026-11-21:** yaw left +57, pitch up +31, roll left +11 /
  right -13 deg, all correct; the earlier "wrong roll sign" came from 3 s windows shorter than the reaction time.
- **Slow events need a minimum duration:**
  - yawn = `jawOpen` above its threshold for **≥ 1.5 s**;
  - gesture held for **≥ 0.5 s**.
- `nodding` (fatigue head drop): raw pitch drops by > 15° in < 1.5 s while the eyes are closed **or were in a
  closure that has not visibly reopened** (`ClosedEyesLatch`, perception/driver_cam/pipeline.py, 2026-11-21):
  - why: with the head pitched down the shut lids often read SQUINT, so "CLOSED on this frame" missed 1 of 2 live
    nods (eval 2026-11-21); the detector never required open eyes, it required CLOSED exactly when the eye tracker
    stops giving it;
  - armed by a closure longer than a blink (`long_closure`; a blink followed by a glance at the lap must not arm it),
    disarmed only by `reopen_min_frames` OPEN frames with r >= `reopen_ratio` (SQUINT / UNKNOWN / no face keep it),
    expires `head.nod.closed_recent_s` (2 s) after the last CLOSED frame;
  - the falling head often leaves the face tracker: gaps up to `head.nod.max_gap_s` (0.5 s) keep the pitch history,
    a pitch beyond the plausible limit **downwards** (yaw / roll plausible) still feeds it, and a detected nod is held
    `head.nod.hold_s` (1 s), frames without a face included;
  - limitation: a fast nod where the eyes close **with** the fall (no closure may start while the head moves) does
    not arm the latch; `closed_ms` and PERCLOS stay P2's primary fatigue signals. Verified on synthetic sequences only
    (the labelled live session with nods was not kept).
- **Head answer** (`head.answer`), only while core has the dialog window open:
  - ≥ 2 direction reversals in < 1.2 s, with the eyes open;
  - pitch reversals = yes, yaw reversals = no.
- `speaking` (`perception/driver_cam/mouth.py`): standard deviation over 1 s of the inner-lip gap (13–14) divided by
  the face height (10–152) ≥ `speaking.lip_std_threshold` (0.003), **and** at least `speaking.min_reversals` (2)
  direction changes of the gap (steps ≥ `speaking.reversal_step`) in the window (speech oscillates; a yawn opens and
  closes once), and never during or within one window after a wide-open jaw. **Held** for `speaking.hold_ms`
  (800 ms) after the last oscillating window, so pauses between words do not drop it. Diag session: rest
  `lip_std` p90 0.0007, reading p50 0.0087; the old 0.008 caught 3 of 5 sentences, 0.003 catches 5 of 5 with a
  median 0.5 s from the first lip movement. The eval scores speaking per **segment** (detected < 1 s after the lips
  leave their rest level), not per frame.

### 3.4 Gaze zones: MobileGaze + kNN
Code: `perception/driver_cam/gaze_model.py`, `gaze_zones.py`, `gaze_metrics.py`, `perception/calibration.py`;
tools `scripts/calibrate.py`, `scripts/eval_zones.py`.

- **Why a gaze model.** Euro NCAP distinguishes **owl** glances (the head turns) from **lizard** glances (only the
  eyes move). Head pose alone misses lizard glances: a glance down at a phone in the lap, or a quick look at the
  mirror. We add **MobileGaze MobileOne-S0** (ONNX, `yakhyo/gaze-estimation`), a lightweight appearance-based gaze
  estimator, at `rates.gaze_hz` (15) on the driver camera only.
- **Pre-processing checked in the repo's code** (`onnx_inference.py`, 2026-11-21), not assumed:
  - crop = the face detector box (RetinaFace there), **no expansion, no squaring**; here the landmark face-oval box x
    `gaze.crop_expand` (1.0). The old inline code used 1.2; `scripts/eval_zones.py --ab-crop` compares both on the
    same live frames (jitter with the gaze still, Fisher separation road vs. mirrors / lap / cluster);
  - BGR -> RGB, `cv2.resize` to 448 x 448 (bilinear), / 255, ImageNet mean / std, NCHW float32;
  - decoding: softmax over 90 bins x 4 - 180 = degrees; outputs read **by name** (the export orders them yaw, pitch);
  - the released weights are trained on **Gaze360 only**.
  - Unit tests compare our pre-processing and decoding with a transcription of theirs (`tests/perception/test_gaze_model.py`).
- **Signs.** The FeatureFrame keeps the raw model angles; `GAZE_SIGNS` maps them to the head convention (yaw > 0 =
  driver's left, pitch > 0 = up). yakhyo draws on a mirrored webcam image, so on our non-mirrored frames the raw yaw
  is reversed: measured on the laptop session 2026-11-21 (1899 frames), corr(head yaw, raw gaze yaw) = **-0.51**,
  corr(head pitch, raw gaze pitch) = **+0.65**. `eval_zones` re-checks both live (`sign_ok`).
- **Smoothing.** One Euro on the driver-convention yaw / pitch (`filters.one_euro_gaze`); between model runs the last
  value is used for at most `gaze.max_age_ms`, then the zone is `unknown`. Raw yaw std with the head still: 4.3 deg.
- **Features (14)**, one function for calibration and runtime (`GazeFeatureBuilder`):
  - head yaw / pitch, **unfiltered** (the head One Euro is tuned for jitter, min cutoff 0.05 Hz, and lags fast
    glances; the raw noise, 0.1-0.2 deg, is negligible next to the zone spacing);
  - MobileGaze yaw / pitch (smoothed);
  - the 8 `eyeLook{In,Out,Up,Down}{Left,Right}` blendshapes;
  - the iris offset (centres 468 / 473) from the eye-corner midpoint, in eye widths (x > 0 = driver's left, y > 0 =
    up), averaged over the reliable eyes (`eyes.min_eye_width_px`, `eyes.unilateral_width_ratio`).
  - **No features -> `unknown`, never a guessed zone:** no face, R-FL3 `face_too_small`, face confidence below
    `filters.unknown_below_conf` (R-FL2), implausible head angles, no fresh gaze, no reliable eye. Squinted eyes
    (R-FL4) stay valid. The reason is reported (`driver.gaze.reason` in the worker state, overlay).
- **Classifier:** z-score with the calibration mean / std (std floored per group, `gaze.std_floor`), group weights
  (`gaze.feature_weights`: the 8 correlated eyeLook features at half weight), distance-weighted kNN (k = 5, 1/d).
- **Rejection:** mean distance to the k neighbours > tau, or vote share < `gaze.min_conf`.
  - tau = p95 of the **blocked leave-one-out** distances of the calibration samples x `gaze.reject_factor`. Each sample
    is classified without the frames of its own calibration segment closer than `gaze.loo_exclude_s` (0.5 s).
    Leaving out only the sample compares it with its near-identical neighbour frames (tau far too small, everything
    unknown live); leaving out the whole segment leaves road (one segment) without road neighbours (tau inflated,
    LOO accuracy meaningless: 11 % on synthetic data before this fix, 100 % after).
  - A rejected frame with the head beyond the calibrated range by `gaze.away_margin_deg` is **`away`** (off-road);
    otherwise **`unknown`**, which never triggers an alert.
- **Stable zone** (`ZoneTracker`): a new zone after `gaze.zone_min_frames` frames (3, ~100 ms at 30 fps, inside the
  300 ms budget); during a blink (`CLOSED`) the previous zone is held for at most `eyes.blink_max_ms`.
- **Calibration** (`scripts/calibrate.py --name <n>` or the `calibrate` command from core; same state machine,
  `CalibrationRun`):
  - per zone: OWL then LIZARD, `gaze.calibration.s_per_zone` (2 s) each; road x `road_factor` (3); passenger = the
    passenger's hands; "back to the road" (`transition_s`) between steps, not recorded; the first `discard_s` (0.3 s)
    after every prompt dropped; frames without features and closed-eye frames not used; a step with fewer than
    `min_samples_per_zone` samples is repeated once, then reported missing. ~1 min 10 s in total;
  - saved to `profiles/<name>/calibration.json` (gitignored): the raw samples (so k / weights / reject factor from
    the yaml apply on load without recalibrating), the blocked-LOO confusion matrix, the open-eye **EAR baseline**
    (p90 per eye on the road samples, given to the eye detector as the global reference) and a per-zone EAR reference
    (stored for `EarReference.get(side, zone)`, not used yet);
  - warnings when the LOO shows road <-> mirror_left or passenger <-> mirror_right confusions;
  - **quick recalibration** (`--quick` / `quick: true`, ~15 s): road + the three mirrors, merged into the profile;
  - the active profile: `gaze.default_profile` at start, then the last calibrated one (identity: step 4).
- **Window metrics** (`gaze_metrics.py`), on the stable zone:
  - **`off_road_ms`** = the current continuous time away from `gaze.on_road_zones` (a run of glances, broken only by
    the road; `away` counts). **Mirror rule:** a glance at a `gaze.mirror_zones` zone is part of driving and counts
    only once it lasts longer than `gaze.mirror_glance_max_ms` (2 s), then from its start. **`unknown` freezes** the
    counter (adds nothing, resets nothing); a lost face is the monitoring rule's job ("Nu te mai văd");
  - **`vats_60s`** = completed off-road runs shorter than `vats_max_glance_s` (2 s) in the last 60 s; short mirror
    glances are not off-road, so not counted. Extra: `off_road_60s_ms`;
  - **`entropy_60s`** = Shannon entropy (bits) of the time-weighted zone distribution over 60 s, `unknown` excluded;
  - **lap pattern** (AS7): >= `phone.lap_pattern.min_glances` (3) glances at `lap` in `window_s` (20 s), or one longer
    than `long_glance_s` (2 s), with no hand seen in the last `hands_recent_s`. The gesture model runs only inside
    the dialog window, so "not run" counts as not seen. `driver.phone` = `source: "lap_pattern"`, `conf =
    phone.lap_pattern.conf` (0.40) **only when the YOLO vote sees no phone**.
- **Evaluation** (`scripts/eval_zones.py`): every zone 5x owl + 5x lizard (road 5x) in random order (seed saved),
  2.5 s each + 1.5 s back to the road (~5 min), post-it targets on the laptop. Trials are scored from the movement
  onset (raw head > 4 deg or gaze > 8 deg away from the 0.5 s before the prompt) + 0.3 s; latency = onset -> first
  frame with the target zone. Report: confusion matrix, owl / lizard accuracy, watched confusions, latency, signs
  (`docs/eval/zones-<name>-<date>.md`). `--session` replays a recorded session; `--sweep` re-runs only the classifier
  on the stored features over k / reject factor / eyeLook weight / zone_min_frames (one session: check the winner
  on a second live session). Exit criteria: owl >= 95 %, lizard >= 90 %, road <-> mirror_left 0, passenger <->
  mirror_right <= 5 %, latency < 300 ms (median).
- **Cost** (laptop, 2026-11-21, runtime): MobileGaze crop + pre-processing + inference **~22 ms p50** on OpenVINO CPU
  (~18 ms alone), every 2nd frame; zone features + kNN + metrics < 1 ms.

### 3.5 Hands and gestures: MediaPipe Gesture Recognizer
- `Thumb_Up`, `Thumb_Down` and `Open_Palm`, run only inside the dialog window or when a hand is raised.
- Gesture Recognizer also returns **21 hand landmarks**. We use them as the hand positions for the phone geometry,
  so we do not need a separate pose model for wrists.
- **YOLO26-pose is used only for `rear_seat`** (AS13, an S feature), at a low rate, as a second confirmation.

### 3.6 Phone: YOLO26 + geometry + voting
- **Model choice, live on the C615 (2026-11-21, `scripts/phone_compare.py`, `docs/eval/phone-compare-2026-11-21.md`):**
  same frames, threshold = lowest with zero false frames on "no phone" / "wallet". Detection at the ear / chest /
  lap / shown from the side: YOLO26n@416 3 / 99 / 0 / 76 %, n@640 1 / 45 / 0 / 59 %, **s@640 58 / 100 / 54 / 100 %**
  -> `models.phone_cpu: yolo26s@640`, `phone.conf_min: 0.48` (wallet peaked at 0.46). Inline, s@640 dropped the driver
  face to 20 fps; it now runs in its own thread (`phone.async_inference`, boxes 1-2 frames older, the 3-of-5 vote
  absorbs it) capped at `models.phone_threads: 2` -> driver face 30 fps, no degradation.
- **Ultralytics YOLO26, COCO class 67** (`cell phone`):
  - on CPU: the `n` model at 416 px;
  - on GPU: the `s` model at 640 px.
  - Rate: 5 Hz.
- **Geometry:** the phone box near a hand (hand landmarks) and near the face (face box) → `near_face`;
  `side` = which side of the driver it is on (left / right).
- **Temporal voting:** the phone counts as in use only if it is seen in **3 of the last 5** YOLO runs. This removes
  single-frame flickers.
- **Lap pattern:** ≥ 3 glances to `lap` in 20 s, or one glance > 2 s, with no hands visible →
  `phone.source = "lap_pattern"`, with a lower confidence.
- **Later:** fine-tune on our own frames (~150, from the demo setup), recorded **only of team members, with their
  consent**, kept locally, never committed.

### 3.6b Posture (`perception/posture.py`, both seats, no extra model)
- Compared with a **reference**: the driver's comes from the calibration (`road` samples: median face centre, face
  width, yaw / pitch / roll -> `posture_ref` in the profile); the passenger's (or an uncalibrated driver's) is the
  median of the first `posture.auto_ref_s` (10 s) with the face seen. Distances in reference face widths, so the rules
  hold at any resolution and seat distance.
- `leaning_forward` (width >= 1.20 x), `leaning_side` (centre >= 0.6 widths sideways or roll >= 15 deg), `slumped`
  (centre >= 0.4 widths lower AND pitch down >= 10 deg), `out_of_position` (>= 1.2 widths away or width outside
  0.6-1.6 x); each held `min_duration_s` (1 s). Starting values; the live 60 s check gave 4 false passenger events
  (automatic reference) -> to tune.

### 3.7 Identity: YuNet + SFace
- `cv2.FaceDetectorYN` (YuNet) + `cv2.FaceRecognizerSF` (SFace), from OpenCV Zoo.
- Match if cosine similarity ≥ **0.363** (OpenCV's recommended value for SFace).
- Runs when a face appears, then re-checks every ~10 s.
- Enrollment: `scripts/enroll_face.py --name andrei` → 10 frames → `profiles/andrei/face.npy`, gitignored.

## 4. Inference runtime

- **CPU threads (2026-11-21):** `models.onnx_threads` (4) now caps native OpenVINO too (`INFERENCE_NUM_THREADS`; before,
  OpenVINO took every core and starved the face), and `OnnxModel(threads=)` overrides it per model
  (`models.phone_threads: 2` for the phone detector running in its own thread).
- `perception/runtime.py` (`OnnxModel`) picks the first provider that works: **CUDA → OpenVINO → CPU** (the order
  is set in yaml, `models.onnx_providers`). A provider that fails to initialize is skipped with a warning; ORT's silent
  fallback to CPU is detected and treated as a failure, so the reported provider is always the one really used.
  - **CUDA:** `onnxruntime-gpu` with the CUDA/cuDNN libraries from pip (`requirements/p1-gpu.txt`).
  - **OpenVINO:** ORT's OpenVINO EP if that build is installed, otherwise the **native `openvino` runtime** on the
    same `.onnx`. `onnxruntime-gpu` and `onnxruntime-openvino` are separate wheels that cannot coexist, so native
    OpenVINO is how one environment gets both.
  - The ONNX models (MobileGaze, the YOLO exports) go through it. YuNet/SFace run in OpenCV DNN; MediaPipe runs its
    own TFLite runtime.
- `OnnxModel.run()` is **inference only**. Pre-processing (`perception/preprocess.py`: letterbox, gaze input) and
  post-processing (`perception/postprocess.py`: YOLO26 NMS-free decoding, gaze bins → degrees) are separate functions,
  timed separately by the benchmark.
- **Why ONNX / TFLite:** both formats can be moved to automotive hardware and quantized (INT8) without rewriting the
  pipeline. That is the bridge to section 7.
- **Measured, not assumed** ([`docs/benchmark/`](benchmark/), `scripts/benchmark.py`, live frames). On the dev laptop
  (Ryzen 7 170 + RTX 4050): the GPU only pays off for the larger model. YOLO26s@640 takes 16.8 ms on CUDA vs 51.8 ms
  OpenVINO / 75 ms CPU, but the small models are *slower* on CUDA (YOLO26n@320: 15.4 ms CUDA vs 6.9 ms OpenVINO;
  MobileGaze p95 15.4 ms CUDA vs 8.2 ms OpenVINO) because of transfer and launch overhead. So the provider is chosen
  **per model**, not one global order: small models on OpenVINO/CPU, YOLO26s on CUDA.
- Warm-up at start-up: one inference per model, before the first frame is published.
- **Timing:** each model call is wrapped in `time.perf_counter()`, with a `deque(maxlen=120)` per model for p50/p95,
  reported in `perf.*_ms_*`.

## 5. Data policy

- **In operation, no images are recorded.** Frames live in memory only, and the MJPEG preview is streamed, never stored.
- **For development and evaluation:** we record **features, never pixels**, so detectors can be tuned and tested on
  real data, repeatably.
  - `perception/features.py`, **`FeatureFrame`**: what the models extract from one frame, *before* detectors and
    filters: time, a fixed subset of face landmarks (eyes, iris, mouth, face oval), all 52 blendshapes, the head
    matrix, MobileGaze angles, hands + gestures with scores, phone boxes, face presence / confidence / width.
  - `perception/recorder.py` writes them to JSONL (optionally gzip), with session metadata: camera, resolution, fps,
    model files + SHA-256, package versions, the config used, a session label.
  - `scripts/label_session.py` records live **and** lets you press keys to mark real events (blink, eyes closed, yawn,
    speaking, gaze zone, phone): the ground truth for evaluation, aligned to the same session clock.
  - `perception/replay.py` reads a session back with its original timing (or faster) as input for detectors, tests,
    evaluation and threshold tuning.
  - Sessions live in `data/features/<session>/` (gitignored; `data/README.md` explains the layout).
- **Replay is never used in the demo (R3).** The demo always runs on the live camera. Replay exists only for
  development, evaluation and tuning; the code warns about it too.
- **Phone fine-tuning data:** team members only, with explicit consent, stored locally, **never in the repo**, deleted after the hackathon.
- **DMD (Driver Monitoring Dataset):** only unrestricted subjects, **evaluation only** (no training), under the
  CC BY-NC-ND 4.0 licence. Nothing derived from it (crops, labels, weights) goes into the repo.
- Face embeddings (`face.npy`) and calibrations stay on the laptop (gitignored).

## 6. Licences (check before the demo / slide)

| Component | Licence | Note |
|---|---|---|
| MediaPipe (Face Landmarker, Gesture Recognizer) | Apache-2.0 | OK. |
| OpenCV + OpenCV Zoo models (YuNet, SFace) | Apache-2.0 / per-model licence | Check the licence file of each model in OpenCV Zoo. |
| Ultralytics YOLO26 | **AGPL-3.0** | Fine for a public hackathon repo. A product needs an Ultralytics enterprise licence or another detector. |
| MobileGaze (`yakhyo/gaze-estimation`) | code: MIT | **Weights trained on Gaze360 only (README); Gaze360 is released for research use: check before any commercial use. Fine for the hackathon demo; name it on the slide.** |
| open-closed-eye-0001 (Intel Open Model Zoo, eye-state CNN) | Apache-2.0 (`openvino_training_extensions`) | Trained on the MRL Eye Dataset (check its terms before a product). |
| DMD | CC BY-NC-ND 4.0 | Evaluation only, nothing derived committed. |

## 7. From demo to a real car

The demo runs on a laptop webcam and a phone. A production version of the same pipeline would change the following:

- **Camera:** a **940 nm NIR** camera with a **global shutter** and **active IR illumination**. It works at night and
  through most sunglasses, ignores the cabin lighting, and has no rolling-shutter blur during head turns.
- **Compute:** a dedicated automotive SoC / NPU running **INT8**-quantized models. The ONNX/TFLite choice in
  section 4 is what makes this a port, not a rewrite.
- **Functional safety (ISO 26262):** the deterministic safety path (perception → rules → local alarm) is **separate**
  from the LLM. The LLM is never on the safety path, which is already how DriveMate is built (P0–P2 are rules only).
- **SOTIF (ISO 21448), perception limits handled explicitly:**
  - every output carries a confidence;
  - low confidence → `unknown`, which never alerts;
  - `eyes.reliable=false` → head metrics only;
  - `monitoring_ok=false` when the face is lost or the frame freezes → "I can't see you".

  The system says when it cannot protect, instead of guessing.

## 8. Differences from the role file

| Topic | `roluri/P1-computer-vision.md` / plan §8 | Decision here | Reason |
|---|---|---|---|
| Capture backend | `cv2.VideoCapture(CAP_V4L2)` | **backend from yaml, `auto` = V4L2 on Linux / DSHOW on Windows**; camera controls via `camera_setup.sh` (Linux) or OpenCV properties (Windows) | The team tests on Windows and Linux laptops; the demo laptop is not fixed yet. |
| Concurrency | one capture thread per camera | **one process per camera** + an asyncio main process | GIL contention between the two cameras and networking; a passenger-camera crash must not stop the driver. |
| Face Landmarker input | crop from the previous landmarks, ×1.6 | **full frame**, VIDEO mode | MediaPipe already tracks the face in VIDEO mode; a manual crop can cut the face during fast turns. |
| Eye-state filter | EMA + hysteresis at fixed 0.18 / 0.23 + 300 ms minimum duration | **median over 3 frames + hysteresis relative to a personal baseline + ≥ 2 frames** | EMA and a 300 ms minimum erase 100–300 ms blinks; fixed thresholds do not fit different eyes or angles. |
| Microsleep | `driver.eyes.microsleep` set by perception | **P1 reports `closed_ms`; P2 decides microsleep** | "P1 reports what it sees, P2 decides what it means"; the safety threshold belongs with the safety rules. |
| Angle filter | EMA | **One Euro filter** | Low lag on fast motion, strong smoothing at rest. |
| Yawn duration | ≥ 2 s | **≥ 1.5 s** | 2 s misses short yawns; 1.5 s is still well above speech. |
| Gaze features | head angles + iris → kNN | **head + MobileGaze + 8 eyeLook blendshapes + iris offset, z-scored, weighted kNN with rejection** | Catches lizard glances (eyes only); rejection gives `unknown` instead of a wrong zone. |
| Calibration | ~2 s per zone | ~2 s per zone, **owl and lizard** | The classifier must have seen both ways of looking at each zone. |
| Wrists / hands | YOLO26n-pose at 5 Hz | **Gesture Recognizer hand landmarks**; YOLO26-pose only for `rear_seat` (S) | Gesture Recognizer is already running; one model fewer in the budget. |
| Phone model | YOLO26n at 640 px, conf > 0.4 | **n at 416 (CPU) / s at 640 (GPU)**, conf > 0.4, **3-of-5 voting**, `near_face`, `side` | Fits the CPU budget; voting removes flicker; the extra fields help P2's cause logic. |
| SFace threshold | ~0.36 | **0.363** | OpenCV's published value. |
| Acceleration | OpenVINO / TensorRT exports | **`perception/runtime.py` over ONNX Runtime** (CUDA / OpenVINO / CPU) | One code path for every machine in the team; portable to automotive hardware. |
| Python | 3.11 | **3.11** (unchanged) | Kept for the whole team; 3.13+ is excluded because of MediaPipe. |

## 9. R4 visibility and proposed contract additions

**R4: every detection must be visible on the live dashboard.** Each R1 detection, the `PerceptionFrame` field that
carries it, and how P4 can show it. "Proposed" fields are sent now (`output.proposed_fields: true`) and listed in
the CONTRACT texts below; with `false` only the plan §7 fields are sent.

| Item (plan 4.A) | `PerceptionFrame` field | Seat | Part A (code + tests, 2026-11-21) | Live GO / NO-GO (part B) | Demo switch |
|---|---|---|---|---|---|
| AS1 landmarks, blendshapes | not in the frame (raw) | both | done | GO (MJPEG `/video/<cam>`, key D) | — |
| AS2 eyes: EAR, blink, PERCLOS, closure | `driver.eyes.ear`, `blink_ms`, `perclos_60s`, `state`, `closed_ms`, `long_closure`, `blink_count`* | driver | two tiers (blink ends at the first open frame, closure after 2 open frames, face gaps <= 200 ms) | pending B (targets 3/3, 9/10) | — |
| R-FL4 squint / smile | `driver.eyes.squint`, `state` | driver | eyeSquint >= `eyes.squint_veto` inside the squint band vetoes "closed" | pending B (target 0/6) | — |
| AS3 yawn | `driver.yawn` | driver | done | pending B (3/3) | — |
| AS4 fatigue nod | `driver.head.nodding` | driver | slow drop: `head.nod.window_s` 3.0 (18 deg in 2.5 s), face gaps, lap look excluded (eyes open) | pending B (>= 4/5) | `demo.nodding_triggers` |
| AS5 gaze zones | `driver.gaze.zone`, `conf`, `source`, `calibrated` | driver | head weight 2.0, unknown hold 0.6 s, calibration warns on OWL steps without a head turn | pending B (owl >= 95 %, lizard >= 90 %) after recalibration | — |
| AS6 VATS, entropy | `driver.gaze.vats_60s`, `entropy_60s`, `off_road_ms`, `off_road_60s_ms` | driver | done (tests) | pending B | — |
| AS7 driver phone, lap pattern | `driver.phone.*`, `driver.gaze.lap_pattern` | driver | done (vote 3/5, near_face / side, passenger's phone foreign) | pending B (>= 95 %) | — |
| AS8 head yes / no | `driver.head.answer`, `passenger.answer` | both | window routed to the addressed seat (close to both), `min_amplitude_deg` 4 (5 deg nods) | pending B (>= 9/10, 0 outside) | `demo.head_answer` |
| AS9 / AP6 gestures | `driver.gesture`, `passenger.gesture` | both | done (window or raised hand) | pending B (>= 95 %) | — |
| AS10 / AP1 identity | `occupants[].profile`, `profile_score` | both | SFace on its own thread (loop never waits), embeddings per camera | pending B (< 3 s) | — |
| AS11 / AP3 speaking | `driver.speaking`, `passenger.speaking` | both | done (hold 800 ms, B9) | pending B | — |
| AS12 / AP5 camera covered | `*.monitoring_ok`, `monitoring_reason = occluded` | both | fast path: no face + very dark / uniform / sharpless for 1 s (a hand passing < 1 s: nothing) | pending B (< 2 s) | — |
| AS13 rear-seat glance (S) | `driver.gaze.zone = rear_seat`, `source = body` | driver | face lost right after a growing right turn -> rear_seat <= 3 s | pending B | `demo.rear_seat` |
| AS14 unreliable eyes (S) | `driver.eyes.reliable` | driver | done (state UNKNOWN, no PERCLOS / nod) | GO | — |
| AP2 passenger asleep | `passenger.awake`, `eyes_closed_s` | passenger | reset only after 3 open frames in a row; closed 8 s is enough, head drop shortens to 5 s | pending B (< 10 s) | — |
| AP4 passenger phone | `passenger.holding_phone` | passenger | done | pending B | — |
| Posture | `driver.posture`*, `passenger.posture`* (always sent, defaults when off) | both | done; passenger off by default | pending B | `demo.posture_driver`, `demo.posture_passenger` |
| Camera selection | `monitoring_reason = "camera_fallback"`* | both | done | GO | — |
| J1 performance | `perf.cameras.*`, `perf.*_ms_p50`, `e2e_ms_p95`, `degrade_level`, `stages_ms`, `publish_ts` | both | every P1 perf field filled (`pose_ms_p50` stays null: no pose model in the runtime) | pending B (face >= 20 fps, both cameras) | — |

\* proposed, not yet in `shared/contracts.py` (contract 2.1): see the CONTRACT block. Everything else is in contract 2.1.
The frame shape never depends on the config: a module switched off keeps its fields at the contract defaults.

### Demo mode (`demo:` in perception.yaml)

A detection that misses its target after two live iterations goes under a switch, off by default, and is marked NO-GO
here with the reason. Switching takes effect at the next start, without code changes.

| Switch | Default | Off means |
|---|---|---|
| `demo.head_answer` | true | no HeadAnswerModule on either camera: `driver.head.answer` / `passenger.answer` stay null |
| `demo.posture_driver` | true | no posture on the driver camera: `driver.posture` all false |
| `demo.posture_passenger` | false | (default) `passenger.posture` all false: not in the scenario, false events with the automatic reference |
| `demo.nodding_triggers` | true | `driver.head.nodding` always false (the head angles are still sent) |
| `demo.rear_seat` | true | AS13 rule off: a lost face stays `unknown` |

Checks: `scripts/demo_check.py` (GO / NO-GO per AS / AP item, ~8 min) and `scripts/scene_check.py` (plan §9 scenes
1-9 + A + AS13 + N); CI locally: `scripts/ci_local.ps1` (same steps as the workflow).

### CONTRACT texts for the group (one block; the only P1 fields still missing from contract 2.1)

All optional with a default, written by P1; `extra="allow"` keeps them valid until P2 adds them.

```
CONTRACT: driver.posture, {"leaning_forward": bool, "leaning_side": bool, "slumped": bool, "out_of_position": bool} (default all false), P1, postura față de referința din calibrare (centrul / lățimea feței + unghiurile capului), fiecare ținută >= posture.min_duration_s; trimisă mereu (valorile implicite când demo.posture_driver e oprit); dashboard + context pentru atenție
CONTRACT: passenger.posture, același tip (default all false), P1, postura pasagerului față de referința automată; trimisă mereu, oprită implicit (demo.posture_passenger)
CONTRACT: driver.eyes.blink_count, int (default 0), P1, număr monoton de clipiri de la pornire: un consumator la 15 Hz nu poate rata o clipire de 150 ms (blink_ms nu se schimbă între două clipiri de aceeași durată)
CONTRACT: MONITORING_REASONS += "camera_fallback", P1, driver/passenger.monitoring_reason când camera rulează pe camera de rezervă de dezvoltare (cameras.dev_fallback), nu pe cea configurată
```

Until P2 decides, `driver.eyes.microsleep` stays `false` from P1.

## 10. Known risks

- **Two OpenCV wheels.** MediaPipe depends on `opencv-contrib-python` and Ultralytics on `opencv-python`; both install
  into the same `cv2` package. After install, check: `python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'FaceDetectorYN'))"`.
- **Windows + GPU.** PyPI's `torch` on Windows is CPU-only. For YOLO on the RTX 4050, install the CUDA build of torch
  (see the commented command in `requirements/p1-perception.txt`). `onnxruntime-gpu` needs matching CUDA 12 and cuDNN 9.
- **DroidCam on Windows** shows up as a virtual webcam (a device index), not as `/dev/videoN`; set the index in yaml.
- **Lighting in the venue:** use our own lamp on the driver; recalibrate on the final setup on Sunday.

## 11. Research basis

The two papers we work from and what they change for us. The PDFs are kept locally by the team, not in this public
repo (copyright); the references below are enough to find them.

### Ersoy, Tatar, Tonbul, Kırbız: "Improving Driver Drowsiness Detection via Personalized EAR/MAR Thresholds and CNN-Based Classification" (MEF University, arXiv 2604.22479, 2026)

What they did: MediaPipe Face Mesh landmarks → EAR, MAR, PERCLOS, head-down; a **5 s calibration** with a neutral face
gives the driver's baseline; thresholds **EAR < 0.75 × baseline**, **MAR > 1.40 × baseline**; compared with fixed
thresholds and with two small CNNs (64×64 eye / mouth crops, CLAHE).

| Result | Fixed threshold | Personalized | CNN |
|---|---|---|---|
| Eye state accuracy | 91.70% | 93.23% | 99.10% |
| Open eyes classified as open | 89.0% | **98.9%** | |
| Yawn detection (yawn class) | 92.5% | **98.4%** | 98.8% (overall) |

What it means for P1:
- **Relative EAR thresholds are confirmed.** The big gain is on *open* eyes (89.0% → 98.9%): fewer open eyes read as
  closed means **fewer false alarms**, which is our main goal. Their single 0.75 sits between our `drop_ratio`
  (0.70) and `reopen_ratio` (0.80).
- Our baseline is a high percentile over `baseline_window_s` (10 s) instead of a 5 s mean, so blinks during
  calibration do not lower it.
- They average over 15 frames before warning. **We do not smooth that much in perception**: it would erase the
  100–300 ms blinks whose duration P2 uses. Decision-level smoothing belongs to P2.
- **Upgrade path:** a small CNN on eye crops (99.1%, with CLAHE) for low light or partial occlusion, behind
  `eyes.reliable`. Not in the M scope.
- Yawn: we use the `jawOpen` blendshape (≈ 0 at rest), so a ratio to the baseline is not meaningful; we keep an
  absolute threshold plus a minimum duration.

### Wang, Li, Li, Zhang, Wu, Zhong, Sebe: "100-Driver: A Large-scale, Diverse Dataset for Distracted Driver Classification" (IEEE T-ITS)

What they did: 470k images, 100 drivers, 5 vehicles, 4 camera views (front-left, front, front-right, side-right),
RGB by day and NIR by night, 22 classes (including talk/text on the phone, left and right); six CNN backbones.

| Finding | Number |
|---|---|
| Same camera, train/test split by driver (Table IV) | ~53–83% accuracy; best views front-left and side-right; night lower than day |
| Cross-view, trained on one camera, tested on another (Table VI) | ~3–52%; front-left → side-right only ~4–7% |
| Cross-vehicle, sedan → van (Table VII) | ~0–33% |
| Cross-modality, day RGB → night NIR (Table IX) | ~4–33%; domain adaptation brings it to ~28–74% (Table X) |
| "Normal driving" class | below 90% in all settings |
| Two-camera fusion (Table V) | up to +8.5 pp; three or four cameras add little or hurt |

What it means for P1:
- **No whole-image "distracted / not distracted" classifier.** Such models collapse when the camera position, the
  car or the lighting changes, and "normal driving" is their weakest class (false alarms). We use **geometry from
  landmarks + per-driver calibration + a generic COCO phone detector**, and we **recalibrate on the final mount**.
- **Camera placement:** front / front-left of the driver gives the best facial cues (yawning is recognised best from
  the front-left view). Keep the laptop webcam in front of the driver, not off to the side.
- **Lighting and modality matter more than the model.** Hence the fixed camera controls (§2.1), our own lamp for the
  demo, and NIR for a real car (§7).
- **Phone left / right:** the dataset separates talking and texting on each side, which supports the `phone.side` and
  `phone.near_face` fields we propose (§9).
- **Two cameras:** fusing two views helps, but more cameras give diminishing returns. Our two cameras have a
  different job (driver + passenger), so we use this only as a general argument, not as a measured claim about our setup.
- The paper quotes the 100-Car study: ~80% of crashes and 65% of near-crashes involved looking away from the forward
  roadway; drowsiness contributed to 12% of crashes and 10% of near-crashes. **Check the primary 100-Car source before
  putting these numbers on a slide.**
