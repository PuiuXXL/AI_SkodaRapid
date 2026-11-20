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
(`CAP_PROP_BUFFERSIZE=1`, MJPG fourcc), stamped with `time.perf_counter()`.

## 3. Detectors

### 3.1 Face: MediaPipe Face Landmarker
- **VIDEO running mode**, on the **full frame**, on CPU. Outputs: 478 landmarks (iris 468–477), 52 blendshapes,
  facial transformation matrix.
- **No manual crop.** In VIDEO mode MediaPipe already tracks the face between frames and runs the detector only
  when tracking is lost. A hand-made crop adds code, can cut off the face during fast head turns, and gains little.
- Driver camera: every frame (target ≥ 20 fps, ≤ 15 ms). Passenger camera: 10 Hz.

### 3.2 Eyes: EAR + eyeBlink, relative thresholds
- **EAR on each eye** (right `33,160,158,133,153,144`; left `362,385,387,263,373,380`), plus the `eyeBlinkLeft/Right`
  blendshapes. The better-seen eye is used and reported in `eye_used`.
- **Thresholds are relative to the driver's personal baseline** (open-eye EAR, a high percentile over a calibration
  window): closed if `EAR < k_close · baseline`, open if `EAR > k_open · baseline`. EAR differs a lot between people
  and camera angles, so a fixed 0.18/0.23 gives false alarms for narrow eyes and missed closures for wide ones.
- **Filtering:** a **median over 3 frames**, then **hysteresis**, then a **minimum of 2 frames** in a state.
  - **No EMA and no 300 ms minimum duration.** Both erase normal blinks of 100–300 ms, and blink duration is one
    of the fatigue signals P2 uses.
- **Outputs:** `ear`, `eye_used`, `blink_ms`, `closed_ms` (current closure duration), `perclos_60s`, `reliable`.
  - **P1 reports `closed_ms`. The microsleep threshold belongs to P2.**
  - `reliable=false` (sunglasses, eyes not visible) → only head metrics are trusted.

### 3.3 Head angles and slow events
- Yaw / pitch / roll from the transformation matrix, smoothed with a **One Euro filter**: little lag on fast
  movements (mirror checks, nods), strong smoothing when the head is still.
- **Slow events need a minimum duration:**
  - yawn = `jawOpen` above its threshold for **≥ 1.5 s**;
  - gesture held for **≥ 0.5 s**.
- `nodding` (fatigue head drop): pitch drops by > 15° in < 1.5 s while the eyes are closing.
- **Head answer** (`head.answer`), only while core has the dialog window open:
  - ≥ 2 direction reversals in < 1.2 s, with the eyes open;
  - pitch reversals = yes, yaw reversals = no.
- `speaking`: variance of `jawOpen` over a 1 s window.

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

- `perception/runtime.py` wraps **ONNX Runtime**, picking the first available execution provider:
  **CUDA → OpenVINO → CPU** (the order is set in yaml).
  - The ONNX models (MobileGaze, YuNet/SFace, the YOLO exports) all go through it.
  - MediaPipe runs its own TFLite runtime.
- **Why ONNX / TFLite:** both formats can be moved to automotive hardware and quantized (INT8) without rewriting the
  pipeline. That is the bridge to section 7.
- Warm-up at start-up: one inference per model, before the first frame is published.
- **Timing:** each model call is wrapped in `time.perf_counter()`, with a `deque(maxlen=120)` per model for p50/p95,
  reported in `perf.*_ms_*`.

## 5. Data policy

- **In operation, no images are recorded.** Frames live in memory only, and the MJPEG preview is streamed, never stored.
- **For development:** we record **feature streams as JSONL** (the `PerceptionFrame` sequence), never video. These are
  also the replay backup for the demo, which is allowed by R3 only as a declared backup.
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

Until P2 decides, `driver.eyes.microsleep` stays `false` from P1.

## 10. Known risks

- **Two OpenCV wheels.** MediaPipe depends on `opencv-contrib-python` and Ultralytics on `opencv-python`; both install
  into the same `cv2` package. After install, check: `python -c "import cv2; print(cv2.__version__, hasattr(cv2, 'FaceDetectorYN'))"`.
- **Windows + GPU.** PyPI's `torch` on Windows is CPU-only. For YOLO on the RTX 4050, install the CUDA build of torch
  (see the commented command in `requirements/p1-perception.txt`). `onnxruntime-gpu` needs matching CUDA 12 and cuDNN 9.
- **DroidCam on Windows** shows up as a virtual webcam (a device index), not as `/dev/videoN`; set the index in yaml.
- **Lighting in the venue:** use our own lamp on the driver; recalibrate on the final setup on Sunday.
