# Perception (P1): technical decisions

> **Status: source of truth for P1.** Where this file disagrees with `roluri/P1-computer-vision.md` or with
> `DriveMate-PLAN-FINAL.md` §8, **this file wins**. Every difference is listed in
> [Differences from the role file](#differences-from-the-role-file), with the reason.
> The JSON contract (`shared/contracts.py`, owned by P2) still wins over both. Contract changes proposed here are
> listed in [Proposed contract additions](#proposed-contract-additions) and must be announced to the team first.

Perception turns the two cameras into a `PerceptionFrame` stream at 15 Hz. **P1 reports what it sees; what it means
(fatigue, risk, alarm) is decided by P2.** Organizer requirements are summarized in
[`hackathon-requirements.md`](hackathon-requirements.md).

---

## 1. Runtime

- **Python 3.11**, the same version for all four modules (as in plan §3), with a single shared `.venv`.
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
| **R-FL4** | **High `eyeSquint` + moderately low EAR = squinting, not closed.** Squinting (sun, smiling, concentrating) lowers EAR without the lids meeting; it must not count in PERCLOS or `closed_ms`. Squint if `eyeSquint ≥ squint_threshold` and `EAR / baseline` lies inside `squint_ear_band`. | `eyes.squint_threshold`, `eyes.squint_ear_band` |
| **R-FL5** | Face Landmarker **does not identify people**: identity is YuNet + SFace only (§3.7). `brow*` blendshapes are optional signals at most, never used for identity or safety decisions. | — |

Face Landmarker exposes **no per-face confidence score** in the Tasks API (landmark `presence` / `visibility` are
`None`), so `FeatureFrame.face.conf` is geometry-based: 1.0 for a face at or above `min_face_width_px`, scaled down
linearly below it, 0 when no face is found.

Measured on the dev laptop webcam (1280×720, normal sitting distance): the face is only **~165 px** wide, below
R-FL3. For the demo, the driver camera must be closer to the face (or have a narrower field of view).

### 3.2 Eyes: EAR + eyeBlink, relative thresholds
- **EAR on each eye** (right `33,160,158,133,153,144`; left `362,385,387,263,373,380`), plus the `eyeBlinkLeft/Right`
  blendshapes. The better-seen eye is used and reported in `eye_used`.
- **Thresholds are relative to the driver's personal baseline** (open-eye EAR, a high percentile over a calibration
  window): closed if `EAR < k_close · baseline`, open if `EAR > k_open · baseline`. EAR differs a lot between people
  and camera angles, so a fixed 0.18/0.23 gives false alarms for narrow eyes and missed closures for wide ones.
- **Filtering:** a **median over 3 frames**, then **hysteresis**, then a **minimum of 2 frames** in a state.
  - **No EMA and no 300 ms minimum duration.** Both erase normal blinks of 100–300 ms, and blink duration is one
    of the fatigue signals P2 uses.
  - Episode durations are measured from the hysteresis **transition times** (first frame of the confirming run), so
    the median and min-frame delays cancel out: a synthetic 150 ms blink is measured as 133–167 ms (± 1 frame).
- Implementation: `perception/driver_cam/eyes.py` (`EyeTracker`), on FeatureFrames (identical live and on replay).
  - EAR in **pixels** (normalized coordinates distort the ratio on 16:9); `eye_used` = the eye with the larger corner
    distance (least foreshortened); `reliable` needs an eye at least `eyes.min_eye_width_px` wide.
  - **Baseline** per eye: from calibration, or provisional = p90 of the first `baseline_window_s` with a valid face,
    usable after `baseline_min_s` (state `UNKNOWN` before); reported as `baseline_provisional`.
  - **Fusion with `eyeBlink`:** when mean(eyeBlinkL, R) ≥ `blendshape_closed` and r is inside the hysteresis band,
    r is pushed below `k_close` (the blendshape confirms what the geometry suggests).
  - **R-FL4 squint, checked first:** max(eyeSquintL, R) ≥ `squint_threshold` and r inside `squint_ear_band` → state
    `SQUINT`, `squint = true`; no PERCLOS, no `closed_ms`, no blink; a closure in progress ends there. The band
    [0.50, 0.80] **deliberately reaches below `k_close` (0.65)**: a broad smile pushes r to ~0.5–0.65, and the exit
    criterion is zero smiles/squints reported as closed. A really closed eye has r < 0.5, so it stays `CLOSED`.
  - Closed episode ≤ `blink_max_ms` → blink (`blink_ms`, `blink_rate` per minute over 60 s); longer → closure.
- **Outputs:** `ear`, `eye_used`, `blink_ms`, `closed_ms` (current closure duration), `perclos_60s`, `reliable`
  (+ `squint`, `state`, `blink_rate`, see §9).
  - **P1 reports `closed_ms`. The microsleep threshold belongs to P2.**
  - `reliable=false` (sunglasses, eyes not visible) → only head metrics are trusted.

### 3.3 Head angles and slow events
- Yaw / pitch / roll from the transformation matrix, smoothed with a **One Euro filter**: little lag on fast
  movements (mirror checks, nods), strong smoothing when the head is still (`perception/driver_cam/head.py`).
- **Axis signs, in the driver's terms:** `yaw > 0` = head turned to the driver's **left** (left mirror);
  `pitch > 0` = head **up**; `roll > 0` = head tilted to the **left shoulder**. MediaPipe's pose is in camera space
  (x = image right, y = up, z = towards the camera, image not mirrored); `AXIS_SIGNS` maps the raw rotations about
  x / y / z to this convention. Unit tests use known rotation matrices; the guided eval (`scripts/eval_eyes.py`,
  "turn left / up / tilt left") checks the signs live and reports `pose_*_sign_ok`.
- **Slow events need a minimum duration:**
  - yawn = `jawOpen` above its threshold for **≥ 1.5 s**;
  - gesture held for **≥ 0.5 s**.
- `nodding` (fatigue head drop): pitch drops by > 15° in < 1.5 s while the eyes are closing.
- **Head answer** (`head.answer`), only while core has the dialog window open:
  - ≥ 2 direction reversals in < 1.2 s, with the eyes open;
  - pitch reversals = yes, yaw reversals = no.
- `speaking` (`perception/driver_cam/mouth.py`): standard deviation over 1 s of the inner-lip gap (13–14) divided by
  the face height (10–152) ≥ `speaking.lip_std_threshold`, **and** at least `speaking.min_reversals` direction
  changes of the gap in the window (speech oscillates; a yawn opens and closes once), and never during or within one
  window after a wide-open jaw (the closing of a yawn would otherwise look like speech).

### 3.4 Gaze zones: MobileGaze + kNN
- **Why a gaze model.** Euro NCAP distinguishes **owl** glances (the head turns) from **lizard** glances (only the
  eyes move). Head pose alone misses lizard glances: a glance down at a phone in the lap, or a quick look at the
  mirror. We add **MobileGaze MobileOne-S0** (ONNX, `yakhyo/gaze-estimation`), a lightweight appearance-based gaze estimator.
- **Features**, standardized with a z-score from the calibration data:
  - head yaw / pitch;
  - MobileGaze gaze yaw / pitch;
  - the 8 `eyeLook{In,Out,Up,Down}{Left,Right}` blendshapes;
  - the iris offset relative to the eye corners (iris centres 468 / 473).
- **Classifier:** distance-weighted kNN, k = 5. **Rejection:** if the nearest calibrated samples are too far away,
  the result is `unknown`. `unknown` never triggers an alert.
- **Calibration** (`scripts/calibrate.py` or the `calibrate` command from core):
  - ~2 s per zone: road, left mirror, right mirror, rear mirror, cluster, infotainment, lap, passenger;
  - each zone is recorded **both owl and lizard** (head turned, then eyes only);
  - saved to `profiles/<name>/calibration.json`, gitignored.
- **Window metrics:** `off_road_ms`, VATS (off-road glances < 2 s, counted over 60 s), and the entropy of the zone
  distribution over 60 s.

### 3.5 Hands and gestures: MediaPipe Gesture Recognizer
- `Thumb_Up`, `Thumb_Down` and `Open_Palm`, run only inside the dialog window or when a hand is raised.
- Gesture Recognizer also returns **21 hand landmarks**. We use them as the hand positions for the phone geometry,
  so we do not need a separate pose model for wrists.
- **YOLO26-pose is used only for `rear_seat`** (AS13, an S feature), at a low rate, as a second confirmation.

### 3.6 Phone: YOLO26 + geometry + voting
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

### 3.7 Identity: YuNet + SFace
- `cv2.FaceDetectorYN` (YuNet) + `cv2.FaceRecognizerSF` (SFace), from OpenCV Zoo.
- Match if cosine similarity ≥ **0.363** (OpenCV's recommended value for SFace).
- Runs when a face appears, then re-checks every ~10 s.
- Enrollment: `scripts/enroll_face.py --name andrei` → 10 frames → `profiles/andrei/face.npy`, gitignored.

## 4. Inference runtime

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
| MobileGaze (`yakhyo/gaze-estimation`) | the code's repo licence | **Check the licence of the weights and of the training data (Gaze360) before using it.** |
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

## 9. Proposed contract additions

Not yet in `shared/contracts.py` (owned by P2). To be announced on the group as `CONTRACT: …`. All optional, with defaults:

| Field | Type | Default | Written by | Why |
|---|---|---|---|---|
| `driver.eyes.closed_ms` | `int` | `0` | P1 | Current closure duration; P2 derives microsleep from it. |
| `driver.phone.near_face` | `bool` | `false` | P1 | Phone held near the face (call / reading) vs. in the hand. |
| `driver.phone.side` | `"left" \| "right" \| null` | `null` | P1 | Which side the phone is on; useful for the cause and the overlay. |
| `driver.eyes.squint` | `bool` | `false` | P1 | R-FL4: squinting / smiling eyes, explicitly *not* closed. |
| `driver.eyes.state` | `"OPEN" \| "CLOSED" \| "SQUINT" \| "UNKNOWN"` | `"UNKNOWN"` | P1 | Discrete eye state for the dashboard and P2's rules. |
| `driver.eyes.blink_rate` | `float \| null` | `null` | P1 | Blinks per minute over 60 s (fatigue signal for F). |
| `driver.face_too_small` | `bool` | `false` | P1 | R-FL3: face narrower than `face.min_face_width_px`; landmarks too coarse. |

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
  closed means **fewer false alarms**, which is our main goal. Their single 0.75 sits inside our hysteresis band
  (`k_close` 0.65 / `k_open` 0.80).
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
