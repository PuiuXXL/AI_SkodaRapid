# P1 modules: hands, head answer, phone, identity, monitoring

> Status 2026-11-21: modules + tests done in the `p1-modules` worktree, **not wired into the runtime yet**.
> Plan refs: roluri/P1-computer-vision.md steps 4 and 6; DriveMate-PLAN-FINAL.md §4.A AS7–AS12 (scenes 1–3: nod for
> the reminder, phone + WhatsApp with 👍, "Nu te mai văd"). Decisions: docs/perception.md (wins over this file).

Every module is a standalone class:

- configuration = a frozen dataclass passed to the constructor, defaults = `perception/config/pending/modules.yaml`
  (`XConfig.from_mapping(section)`; unknown keys are rejected). **No module reads a yaml file.**
- input = a frame + timestamp, or already extracted data (FeatureFrame parts, angles, boxes, hands);
- output = a frozen dataclass with `ms` (execution time, `time.perf_counter`) and `to_dict()` for the worker message;
- models (MediaPipe / ONNX / OpenCV DNN) are created lazily from the config paths or injected (tests use fakes);
- mono / IR frames (`GREY`, `HxW` or `HxWx1`) are expanded to 3 channels before any model (`perception.hands.as_bgr`).
- All `t` / `until` values are seconds on **one** clock. In the worker that clock is `frame.t_capture - t0`, so a
  dialog window's `until_perf` (main process, `perf_counter`) must be passed as `until_perf - t0`.
- Sides are in the **driver's** terms (image not mirrored: image right = the driver's left), as in `head.py`.

---

## De integrat

### 1. Hands and gestures: `perception/hands.py` (AS9 / AP6)

| | |
|---|---|
| Constructor | `HandTracker(HandsConfig.from_mapping(pending["hands"]))` (one per camera); `recognizer=` for tests |
| Inputs | live: `process(frame.image, t, face_box)` (runs the Gesture Recognizer when `should_run(t)`); replay / when the extractor already ran it: `update(t, ff.hands, (w, h), face_box)`. `face_box = face_box_px(ff.face, w, h)` (`perception/driver_cam/face.py`). Dialog: `set_dialog(open, until)` |
| Outputs | `HandsResult`: `gesture` (held >= `min_ms`), `gesture_score`, `held_ms`, `candidate`, `hands` (each `Hand`: handedness, score, gesture, `wrist_px`, `palm_px`, `box_px`, `raised`), `ran`, `mode` (background / dialog), `last_hand_t`, `ms` |
| PerceptionFrame | `driver.gesture` / `passenger.gesture` = `gesture`; `perf.gesture_ms_p50` from `ms` when `ran`; proposed `driver.gesture_score` |
| Rate | background `background_hz` 2 Hz (hand positions for the phone, lap pattern "hands seen", raised hand); dialog `dialog_hz: 0` = every frame. Gesture Recognizer costs **18 ms p50** (docs/benchmark): if the driver frame budget suffers, set `dialog_hz: 15` (what the worker uses today) |
| Overlay | 21 landmarks or at least wrist + palm dots per hand, `candidate` + held bar (`held_ms / min_ms`), the held gesture as an icon (👍 👎 ✋), `mode` |
| Replaces | `GestureHold` in `perception/worker.py` and the gesture on/off in `FeatureExtractor.set_gesture` (the tracker decides the rate; call `extractor.set_gesture(...)` from `tracker.rate_hz(t)` or move the recognizer out of the extractor) |
| Lap pattern | `GazeMetrics` needs "hands seen recently": use `last_hand_t` (background rate keeps it fresh) instead of "gestures only run in the window" |

### 2. Head answer: `perception/driver_cam/head_answer.py` (AS8)

| | |
|---|---|
| Constructor | `HeadAnswerDetector(HeadAnswerConfig.from_mapping(pending["head_answer"]), seat="driver" or "passenger", person_id=occupants[].id)` |
| Inputs | **every frame**: `update(t, state.head.raw_yaw, state.head.raw_pitch, eyes_open)` with `eyes_open = None if not state.eyes.reliable else state.eyes.state != "CLOSED"`. Use the **raw** angles: the head One Euro (min_cutoff 0.05 Hz) damps 2–3 Hz nods. `dialog_window` command -> `open_window(open, to, until)` (returns whether it is for this seat) |
| Outputs | `HeadAnswerResult`: `answer` ("yes" / "no" / None, held `answer_hold_s`), `active`, `crossings_pitch/yaw`, `rms_pitch/yaw`, `ms` |
| PerceptionFrame | `driver.head.answer` (already in the contract); passenger: `passenger.answer` from a second detector with `seat="passenger"` on the passenger pipeline's raw angles |
| Rate | every frame of that camera (cost < 0.01 ms); the slow mean must run while the window is closed too |
| Overlay | while `active`: "DIALOG" badge, the two crossing counters and RMS, the answer chip (green yes / red no) |
| Notes | a single nod (one down-up) is 1 crossing = no answer, by the AS8 rule (>= 2 reversals) |

### 3. Phone: `perception/phone.py` (AS7 / AP4)

| | |
|---|---|
| Constructor | `PhoneDetector(PhoneConfig.from_mapping(pending["phone"]))` (picks n@416 CPU / s@640 GPU via `device`, `OnnxModel` from `perception/runtime.py`) and `PhoneTracker(cfg)` (one per camera) |
| Inputs | detector: `if det.should_run(t): boxes = det.detect(frame.image, t).boxes` else `None`; tracker: `update(t, boxes or ff.phones, face_box=face_box, hands=hands_result.hands, lap_pattern=state.gaze.lap_pattern)` |
| Outputs | `PhoneResult`: `in_use`, `conf`, `source` ("detector" / "lap_pattern"), `usage` ("call" / "hand" / "visible" / "lap"), `near_face`, `side`, `box`, `foreign`, `foreign_box`, `votes`, `runs`, `ran`, `ms` (geometry); `PhoneDetections.ms` (YOLO incl. letterbox + decode) |
| PerceptionFrame | `driver.phone.in_use / conf / source`; proposed `driver.phone.near_face`, `side` (§9 CONTRACT, already announced), `usage`, `foreign_seen`; passenger: `passenger.holding_phone = in_use`; `perf.phone_ms_p50` from `PhoneDetections.ms` |
| Rate | `rate_hz` 5 Hz; the degradation rule calls `detector.set_rate_hz(hz)` (down to 1.25 Hz); the vote is per YOLO run, so it stays valid |
| Overlay | voted box (red when `in_use`) + usage label, `foreign_box` in grey with "not driver", vote `votes/runs`, near-face circle (`near_face_ratio` x face width) |
| Replaces | `PhoneVoter` in `perception/worker.py`, the YOLO block of `FeatureExtractor.extract` (or keep the extractor for recording and feed `ff.phones` to the tracker), and the lap-pattern merge in `perception/main.py` (the tracker already applies "lap only without a voted phone") |
| Passenger camera | ownership needs the driver's face: on the passenger camera call `update(..., face_box=passenger_face_box)` with `passenger_side` = the side where the driver appears in that image, or `face_box=None` (votes without ownership) |

### 4. Identity: `perception/identity.py` + `scripts/enroll_face.py` (AS10 / AP1)

| | |
|---|---|
| Constructor | `FaceIdentifier(IdentityConfig.from_mapping(pending["identity"]), FaceGallery.load(REPO_ROOT / "profiles", camera), camera=camera)` (one per camera) |
| Inputs | every frame: `update(t, frame.image, face_present=ff.face.present)`; it runs YuNet + SFace only on a new face, every `recheck_s`, or `retry_s` after a YuNet miss |
| Outputs | `IdentityResult`: `profile` (held), `score`, `best`, `ran`, `reason` (matched / unknown_face / no_face / no_gallery / held / no_image), `ms` |
| PerceptionFrame | `occupants[seat=driver|front_right].profile`; proposed `occupants[].profile_score`; `perf.sface_ms_p50` from `ms` when `ran`; the active gaze profile can follow `profile` (`gaze.default_profile` today) |
| Rate | event-driven: ~1 run / 10 s per camera, YuNet 24 ms + SFace 6 ms (benchmark). If that spike matters, downscale the frame to 640 px before `update` (YuNet boxes are only used for `alignCrop` on the same image) |
| Overlay | name + score on the occupant label, "?" for `unknown_face` |
| Enroll command | `enroll {name, camera}`: in the worker of that camera, feed `Enroller(identifier).offer(t, frame.image)` per frame until `done`, then `finish()` + `Enroller.save(...)`, reload the gallery. Ack `started`, progress (count / needed / reason), `done` / `error` |
| Enroll script | `python scripts/enroll_face.py --name andrei --camera driver` (opens the camera from perception.yaml; `--device` overrides). **Not run in this session (no live camera).** |
| Storage | `profiles/<name>/face_<camera>.npy`, `face.npy` = fallback for both cameras (`FaceGallery.fallback`). `.gitignore` now has `profiles/*/face*.npy` |

### 5. Monitoring: `perception/monitoring.py::CameraMonitor` (AS12 / AP5)

| | |
|---|---|
| Constructor | `CameraMonitor(CameraMonitorConfig.from_mapping(pending["monitoring"]))` (one per camera) |
| Inputs | every frame: `update(t, frame.image, face_present=ff.face.present, face_width_px=ff.face.width_px)`; no frame (status heartbeat): `tick(t)`; a dead worker = `no_frames` in the main process |
| Outputs | `MonitoringResult`: `ok`, `reason`, `warnings` (too_dark, blurred, face_too_small), `face_too_small`, `confidence`, `face_missing_s`, `luma`, `std`, `sharpness`, `chroma`, `mode` (color / mono), `mode_switched`, `ms` |
| PerceptionFrame | proposed `driver.monitoring_ok` = `ok`, `driver.monitoring_reason` = `reason` (new vocabulary, CONTRACT below), `driver.face_too_small`, proposed `driver.monitoring_warnings`, `driver.camera_mode`; passenger: `passenger.present = ok`, `passenger.monitoring_reason` |
| Rate | every frame (~0.1–0.5 ms on 720p: one 160 px resize + Laplacian) |
| Overlay | red banner "Nu te mai văd: <reason>" when not ok, amber warnings, luma / sharpness / mode numbers in debug |
| On `mode_switched` | reset what depends on the image: `EarReference`, One Euro filters, `CameraMonitor` is already handled; the gaze calibration was made in one mode and may not hold in the other |
| Replaces | `Monitor` + `MonitorState` (kept untouched because `worker.py` imports them). Delete them after the switch |

Reason mapping, old (`Monitor`, docs/perception.md §9) -> new (`CameraMonitor`):

| old | new | note |
|---|---|---|
| `camera_unavailable` | `no_frames` | also "frames stopped for `no_frames_s`" |
| `camera_frozen` | `frozen` | same sparse-sample check |
| `camera_covered` | `occluded` | now "uniform image" (std < `occluded_std_max`), not just "dark" |
| (none) | `too_dark` | face missing in a dark but structured image |
| (none) | `blurred` | face missing in a blurred image |
| `face_lost` | `face_lost` | nothing wrong with the image |
| (none) | `mode_switch` | IR day/night switch, `mode_switch_hold_s` |

Darkness / blur with the face still seen are **warnings only**: a working face detector is the best evidence that
monitoring works. R-FL3 (`face_too_small`) lowers `confidence` and never sets `ok = false`.

### 6. Configuration move

Every `pending/modules.yaml` key marked `(= perception.yaml ...)` duplicates an existing value; at integration add the
sections to `perception/config/perception.yaml` + `perception/config.py` and keep one value. New keys: hands
`background_hz`, `dialog_hz`, `dropout_ms`, `max_gap_s`, `raised_*`; head_answer `slow_tau_s`, `dominance_ratio`,
`max_closed_ms`, `answer_hold_s`, `max_gap_s`; phone `hand_radius_ratio`, `foreign_dx_ratio`, `passenger_side`,
`mirrored`, model paths; identity `top_k`, `min_face_px`, `retry_s`, `lost_s`, `enroll_*`; monitoring `no_frames_s`,
`occluded_std_max`, `blur_var_min`, `mono_chroma_max`, `mode_switch_*`, `analysis_width`.

### 7. Outside this worktree's files

- `pyproject.toml`: add `"scripts/eval_interaction.py"` to `[tool.ruff] include`, and `"scripts/enroll_face.py",
  "scripts/eval_interaction.py"` to `[tool.mypy] files` (both scripts pass ruff + mypy strict when given explicitly).
- `docs/perception.md` to update (proposed): §3.7 embeddings per camera (`face_<camera>.npy`, `enroll_face.py --camera`);
  §2.2 / §9 the new monitoring reasons; §3.5 background hand rate (positions for the phone, "hands seen" for the lap
  pattern) + `dropout_ms`; §3.3 head answer method (slow mean + Schmitt crossings, raw angles); §3.6 `usage`, `foreign`.
- `.gitignore`: done here (`profiles/*/face*.npy`, approved).
- `tests/perception/test_pipeline.py::test_latest_real_eval_session_meets_minimums` already fails before these changes
  (this worktree's `data/features` only has the two oldest sessions; the latest one fails `squint_smile`).

### CONTRACT texts for the group

New, all optional with a default, written by P1 (near_face / side / monitoring_ok / face_too_small are already in
docs/perception.md §9 and are not repeated):

```
CONTRACT: driver.phone.usage, "call"|"hand"|"visible"|"lap"|null (default null), P1, cum e folosit telefonul: la ureche / în mână / văzut fără mână / tiparul „poală”; P2 îl poate folosi pentru cauză (B4)
CONTRACT: driver.phone.foreign_seen, bool (default false), P1, camera șoferului vede un telefon care NU e al lui (din dreapta, departe de față); ca P2 să nu-l confunde cu telefonul șoferului
CONTRACT: driver.monitoring_reason, "no_frames"|"frozen"|"mode_switch"|"occluded"|"too_dark"|"blurred"|"face_lost"|null (default null), P1, înlocuiește lista din §9 (camera_unavailable→no_frames, camera_frozen→frozen, camera_covered→occluded); C7 poate spune motivul
CONTRACT: passenger.monitoring_reason, același tip ca driver.monitoring_reason (default null), P1, de ce camera pasagerului nu-l vede (AP5)
CONTRACT: driver.monitoring_warnings, list["too_dark"|"blurred"|"face_too_small"] (default []), P1, calitatea imaginii e slabă dar fața se vede (monitoring_ok rămâne true); dashboard-ul poate afișa un avertisment
CONTRACT: driver.camera_mode, "color"|"mono"|null (default null), P1, camera e în modul zi (color) sau noapte IR (mono); comutarea dă monitoring_reason="mode_switch" pentru ~1,5 s
CONTRACT: driver.face_conf, float 0..1 (default 0), P1, încrederea feței după lățime (R-FL3: lățime / 250 px); sub prag dashboard-ul cere apropierea camerei
CONTRACT: driver.gesture_score, float|null (default null), P1, scorul gestului ținut (Gesture Recognizer), pentru log și debug
CONTRACT: occupants[].profile_score, float|null (default null), P1, similaritatea cosinus SFace a profilului recunoscut (prag 0,363), pentru debug și fișa călătoriei
CONTRACT: comanda core -> perception "enroll" primește "camera": "driver"|"passenger" (default "driver"), P1, embedding-urile sunt per cameră (profiles/<nume>/face_<camera>.npy)
CONTRACT: ack-ul comenzii "enroll" are status "started", apoi "progress" (detail: count, needed, reason) și "done" (detail: frames, consistency, similar_to) sau "error" (detail cu motivul), P1
```

---

## Evaluation (no live camera in this session)

`scripts/eval_interaction.py` (report in `docs/eval/` by default; the runs below wrote to a scratch dir):

| Run | Result |
|---|---|
| `--synthetic --seed 7` (protocol: 20 answers, 30 gestures, 5 phone situations, 30 s free) | PASS 12/12: yes 9/10, no 10/10, 👍 👎 ✋ 10/10 each, phone 5/5 (incl. passenger phone = not counted), 0 answers outside windows; median latency answer 1.17 s / gesture 1.40 s from the prompt (includes the synthetic 0.5–1.1 s reaction). The missed "yes" was ~1 nod cycle at ~5 deg with a blink on the zero crossing: 1 reversal, correctly rejected by the >= 2 rule |
| `--session 20261121-012736_eval-laptop` (eval_eyes protocol) | 0 answers with no window; window forced open over the whole session: 2 answers (0.7 / min), both real down-up head movements (a +-3 deg settle at 4.6 s, a 17 deg dip-and-return while holding the head up at 23.9 s) |
| `--session 20261121-005208_desk-test-laptop-webcam` | 0 answers with no window; phone vote in use **100 %** of the labelled `phone` interval vs 0.5 % outside; forced window 3 answers (during an unlabelled stretch and a long yawn / phone segment) |

Not validated yet, to do in the live run (`python scripts/eval_interaction.py --name <n> --profile <calibrated>`):

- real nods / shakes / gestures with the real models and reaction times; `min_amplitude_deg` 6 vs 8 (the forced-window
  answers above were 6–17 deg movements);
- the phone geometry with real boxes: `hand_radius_ratio`, `foreign_dx_ratio` (the passenger situation), lap pattern
  needs a calibrated gaze profile;
- monitoring image thresholds (`occluded_std_max`, `blur_var_min`, `mono_chroma_max`, `mode_switch_luma_delta`): the
  recorded sessions hold no pixels, so these are checked on synthetic frames only. Check them live: cover the lens,
  defocus, dark room, and the IR camera's day/night switch if the demo camera has one;
- identity on real faces (enroll both cameras, cross-check that two team members do not match each other).
