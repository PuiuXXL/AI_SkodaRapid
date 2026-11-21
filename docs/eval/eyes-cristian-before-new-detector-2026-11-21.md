# Eye / head / mouth evaluation: cristian-before-new-detector (2026-11-21)

- **mode:** replay of a labelled session
- **session:** 20261121-022040_eval-cristian-before
- **frames:** 6658

## Exit criteria

| Criterion | Result |
|---|---|
| blinks detected >= 95% | PASS |
| false closures <= 1 per minute | PASS |
| 2 s closures detected 100%, closed_ms error < 100 ms | **FAIL** |
| squint / smile reported as closed: 0 | PASS |
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
| blink_ms_median | 166.9 |
| closures_labelled | 3 |
| closures_detected | 2 |
| closed_ms_error_mean | 601.1 |
| closed_ms_error_max | 732.3 |
| false_closures | 1 |
| false_closures_per_min | 0.26 |
| false_closures_look_down | 1 |
| blinks_spontaneous | 8 |
| squint_smile_reported_closed | 0 |
| squint_smile_closed_frames | 0 |
| squint_smile_squint_state_pct | 22.4 |
| yawns_labelled | 3 |
| yawns_detected | 3 |
| false_yawns_while_speaking | 0 |
| speaking_detected_pct | 55.4 |
| speaking_segments | 5 |
| speaking_segments_detected | 5 |
| speaking_onset_latency_ms_median | 495 |
| speaking_coverage_after_onset_pct | 57.3 |
| speaking_during_yawn_pct | 0.0 |
| angle_jitter_deg | {'yaw': 0.03, 'pitch': 0.061, 'roll': 0.153} |
| angle_jitter_raw_deg | {'yaw': 0.081, 'pitch': 0.123, 'roll': 0.184} |
| angle_still_std_deg | {'yaw': 0.961, 'pitch': 2.194, 'roll': 3.751} |
| still_neutral_frames | 218 |
| speaking_false_still_pct | 17.0 |
| too_small_pct_when_close | 95.1 |
| pose_left_yaw_median | 56.6 |
| pose_left_sign_ok | True |
| pose_up_pitch_median | 30.7 |
| pose_up_sign_ok | True |
| pose_tilt_left_roll_median | 10.6 |
| pose_tilt_left_sign_ok | True |
| pose_tilt_right_roll_median | -12.9 |
| pose_tilt_right_sign_ok | True |
| too_small_pct_step_back | 100.0 |
| face_width_px_step_back_median | 161.4 |
| face_width_px_median | 285.7 |
| face_present_pct | 98.3 |
| duration_s | 228.2 |
| frames | 6658 |

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
