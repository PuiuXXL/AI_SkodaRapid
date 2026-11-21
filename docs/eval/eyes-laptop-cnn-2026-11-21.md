# Eye / head / mouth evaluation: laptop-cnn (2026-11-21)

- **mode:** replay of a labelled session
- **session:** 20261121-143356_eval-laptop-cnn
- **frames:** 6368

## Exit criteria

| Criterion | Result |
|---|---|
| blinks detected >= 95% | PASS |
| false closures <= 1 per minute | PASS |
| 2 s closures detected 100%, closed_ms error < 100 ms | **FAIL** |
| eyes closed -> reported CLOSED, median < 300 ms (plan §8 alarm budget) | PASS |
| head drop with closed eyes reported as nodding in every nod window | **FAIL** |
| squint / smile reported as closed: 0 | **FAIL** |
| yawns detected >= 90% | PASS |
| no yawn while speaking | PASS |
| speaking detected in >= 90% of segments (< 1 s after the lips start moving) | PASS |
| angle jitter < 1 deg with the head still | PASS |
| face_too_small shown when stepping back | PASS |

## Metrics

| Metric | Value |
|---|---|
| blinks_cued | 10 |
| blinks_detected | 10 |
| blink_detection_pct | 100.0 |
| blink_ms_median | 154.2 |
| closures_labelled | 3 |
| closures_detected | 3 |
| closed_ms_error_mean | 828.0 |
| closed_ms_error_max | 1415.7 |
| closed_detect_latency_ms_median | 47.5 |
| closed_detect_latency_ms_max | 55.6 |
| nods_labelled | 2 |
| nods_detected | 1 |
| false_closures | 3 |
| false_closures_per_min | 0.66 |
| false_closures_look_down | 0 |
| blinks_spontaneous | 22 |
| squint_smile_reported_closed | 2 |
| squint_smile_closed_frames | 53 |
| squint_smile_squint_state_pct | 9.4 |
| yawns_labelled | 3 |
| yawns_detected | 3 |
| false_yawns_while_speaking | 0 |
| speaking_detected_pct | 58.6 |
| speaking_segments | 5 |
| speaking_segments_detected | 5 |
| speaking_onset_latency_ms_median | 398 |
| speaking_coverage_after_onset_pct | 59.7 |
| speaking_during_yawn_pct | 0.0 |
| angle_jitter_deg | {'yaw': 0.007, 'pitch': 0.022, 'roll': 0.023} |
| angle_jitter_raw_deg | {'yaw': 0.031, 'pitch': 0.108, 'roll': 0.04} |
| angle_still_std_deg | {'yaw': 0.268, 'pitch': 1.225, 'roll': 0.619} |
| still_neutral_frames | 232 |
| speaking_false_still_pct | 0.0 |
| too_small_pct_when_close | 0.0 |
| pose_left_yaw_median | 36.2 |
| pose_left_sign_ok | True |
| pose_up_pitch_median | 35.1 |
| pose_up_sign_ok | True |
| pose_tilt_left_roll_median | 30.4 |
| pose_tilt_left_sign_ok | True |
| pose_tilt_right_roll_median | -40.6 |
| pose_tilt_right_sign_ok | True |
| too_small_pct_step_back | 100.0 |
| face_width_px_step_back_median | 173.6 |
| face_width_px_median | 267.5 |
| face_present_pct | 99.5 |
| duration_s | 271.2 |
| frames | 6368 |

## Thresholds used (perception.yaml)

```yaml
eyes.local_ref_window_s: 4.0
eyes.ref_floor_ratio: 0.6
eyes.drop_ratio: 0.7
eyes.reopen_ratio: 0.8
eyes.fall_max_ms: 150.0
eyes.min_state_frames: 2
eyes.blink_max_ms: 500
eyes.blendshape_closed: 0.45
eyes.unilateral_width_ratio: 0.7
eyes.look_down_threshold: 0.5
eyes.pitch_down_deg: 15.0
eyes.pitch_up_deg: 20.0
eyes.drop_ratio_relaxed: 0.45
eyes.squint_ear_band: [0.5, 0.7]
eyes.closed_level_default: 0.4
yawn.jaw_open_threshold: 0.5
yawn.min_duration_s: 1.5
speaking.lip_std_threshold: 0.003
speaking.min_reversals: 2
face.min_tracking_conf: 0.6
face.min_face_width_px: 250
filters.one_euro_head: {'yaw': {'min_cutoff': 0.05, 'beta': 0.01, 'd_cutoff': 1.0}, 'pitch': {'min_cutoff': 0.05, 'beta': 0.01, 'd_cutoff': 1.0}, 'roll': {'min_cutoff': 0.5, 'beta': 0.005, 'd_cutoff': 1.0}}
```

## Notes

- Ground truth is human timing (cue reaction / key press, ~100-300 ms). closed_ms error compares durations.

## Diagnosis (2026-11-21)

- **Eye-state CNN: OFF** (`eyes.cnn.enabled: false`). Its output was first read inverted (class 0 = closed; fixed,
  `CLOSED_CLASS = 0`; this recording's `eye_closed_p` rewritten as 1 - p, original kept as
  `features-inverted-cnn.jsonl.gz`). Even read correctly it is not reliable on the C615: in the next session
  (`eyes-laptop-closures-2026-11-21.md`) it reported "open" (~1.0) for clearly shut eyes (EAR 0.06), and its veto hid
  4/4 closures; hard squints and big smiles read "closed" 0.6-0.97. A veto that can hide a real closure is a safety
  risk, so the numbers above are EAR + blendshapes only. With the CNN off the eye tracker also ignores recorded
  p(closed).
- **`closed_2s` FAIL = labelling artefact.** All 3 closures are detected (latency median 48 ms) and match the EAR; the
  SPACE presses do not bracket them (eyes closed before the first SPACE in windows 1-2, 2.2 s before it in window 3).
- **`squint_smile` FAIL = known limitation.** The hard squint reaches EAR ratio 0.35-0.49 with eyeBlink 0.52-0.54: a
  grid over `blendshape_closed` 0.45-0.58, `squint_ear_band[0]` 0.40-0.50 and the CNN on all 4 labelled sessions found
  no setting that removes it without losing real closures elsewhere (band 0.40: 0/3 closures in 20261121-022040).
  `tests/perception/test_pipeline.py::test_latest_real_eval_session_meets_minimums` is xfail for this reason.
- **`nodding`.** The old rule ("ratio below reopen_ratio") reported a nod in every look-down window (3/3 in each
  session) and on fast head moves; nodding now needs the eye state CLOSED (look-down 0-1/3, stray nod frames
  150-300 -> 0-39 per session). Limitation: with the head pitched down the shut lids often read SQUINT, so only 1 of the
  4 live nods today is reported; the primary fatigue signals for P2 stay `closed_ms` and PERCLOS.
