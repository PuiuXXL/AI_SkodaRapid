# Eye / head / mouth evaluation: laptop (2026-11-21)

- **mode:** guided live
- **session:** 20261121-012736_eval-laptop
- **camera:** 1280x720 YUY2 @ 30 fps
- **frames:** 3829
- **aborted:** False

## Exit criteria

| Criterion | Result |
|---|---|
| blinks detected >= 95% | **FAIL** |
| false closures <= 1 per minute | **FAIL** |
| 2 s closures detected 100%, closed_ms error < 100 ms | **FAIL** |
| squint / smile reported as closed: 0 | **FAIL** |
| yawns detected >= 90% | PASS |
| no yawn while speaking | PASS |
| angle jitter < 1 deg with the head still | **FAIL** |
| face_too_small shown when stepping back | PASS |

## Metrics

| Metric | Value |
|---|---|
| blinks_cued | 10 |
| blinks_detected | 4 |
| blink_detection_pct | 40.0 |
| blink_ms_median | 863.9 |
| closures_labelled | 3 |
| closures_detected | 3 |
| closed_ms_error_mean | 525.1 |
| closed_ms_error_max | 1057.6 |
| false_closures | 19 |
| false_closures_per_min | 6.83 |
| blinks_spontaneous | 23 |
| squint_smile_reported_closed | 4 |
| squint_smile_closed_frames | 264 |
| squint_smile_squint_state_pct | 17.0 |
| yawns_labelled | 3 |
| yawns_detected | 3 |
| false_yawns_while_speaking | 0 |
| speaking_detected_pct | 26.0 |
| speaking_during_yawn_pct | 0.0 |
| angle_jitter_deg | {'yaw': 0.228, 'pitch': 3.052, 'roll': 0.433} |
| too_small_pct_when_close | 0.0 |
| pose_left_yaw_median | 8.5 |
| pose_left_sign_ok | True |
| pose_up_pitch_median | 25.8 |
| pose_up_sign_ok | True |
| pose_tilt_left_roll_median | -2.5 |
| pose_tilt_left_sign_ok | False |
| too_small_pct_step_back | 100.0 |
| face_width_px_step_back_median | 155.2 |
| face_width_px_median | 271.3 |
| face_present_pct | 99.2 |
| duration_s | 166.9 |
| frames | 3829 |

## Thresholds used (perception.yaml)

```yaml
eyes.k_close: 0.65
eyes.k_open: 0.8
eyes.min_state_frames: 2
eyes.blink_max_ms: 500
eyes.blendshape_closed: 0.55
eyes.squint_threshold: 0.55
eyes.squint_ear_band: [0.5, 0.8]
yawn.jaw_open_threshold: 0.5
yawn.min_duration_s: 1.5
speaking.lip_std_threshold: 0.008
speaking.min_reversals: 3
face.min_tracking_conf: 0.6
face.min_face_width_px: 250
filters.one_euro: {'min_cutoff': 1.0, 'beta': 0.05, 'd_cutoff': 1.0}
```

## Notes

- Ground truth is human timing (cue reaction / key press, ~100-300 ms). closed_ms error compares durations.
