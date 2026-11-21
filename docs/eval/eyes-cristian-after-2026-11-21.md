# Eye / head / mouth evaluation: cristian-after (2026-11-21)

- **mode:** guided live
- **session:** 20261121-025703_eval-cristian-after
- **camera:** 1280x720 YUY2 @ 30 fps
- **frames:** 7314
- **aborted:** False

## Exit criteria

| Criterion | Result |
|---|---|
| blinks detected >= 95% | **FAIL** |
| false closures <= 1 per minute | **FAIL** |
| 2 s closures detected 100%, closed_ms error < 100 ms | not measured |
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
| blinks_detected | 8 |
| blink_detection_pct | 80.0 |
| blink_ms_median | 143.8 |
| false_closures | 8 |
| false_closures_per_min | 1.93 |
| false_closures_look_down | 1 |
| blinks_spontaneous | 11 |
| squint_smile_reported_closed | 3 |
| squint_smile_closed_frames | 33 |
| squint_smile_squint_state_pct | 14.4 |
| yawns_labelled | 3 |
| yawns_detected | 3 |
| false_yawns_while_speaking | 0 |
| speaking_detected_pct | 53.8 |
| speaking_segments | 5 |
| speaking_segments_detected | 5 |
| speaking_onset_latency_ms_median | 436 |
| speaking_coverage_after_onset_pct | 55.9 |
| speaking_during_yawn_pct | 0.6 |
| angle_jitter_deg | {'yaw': 0.006, 'pitch': 0.007, 'roll': 0.028} |
| angle_jitter_raw_deg | {'yaw': 0.018, 'pitch': 0.058, 'roll': 0.048} |
| angle_still_std_deg | {'yaw': 0.201, 'pitch': 0.21, 'roll': 0.407} |
| still_neutral_frames | 258 |
| speaking_false_still_pct | 0.4 |
| too_small_pct_when_close | 0.0 |
| pose_left_yaw_median | 31.4 |
| pose_left_sign_ok | True |
| pose_up_pitch_median | 32.3 |
| pose_up_sign_ok | True |
| pose_tilt_left_roll_median | 24.9 |
| pose_tilt_left_sign_ok | True |
| pose_tilt_right_roll_median | -40.3 |
| pose_tilt_right_sign_ok | True |
| too_small_pct_step_back | 100.0 |
| face_width_px_step_back_median | 158.9 |
| face_width_px_median | 301.1 |
| face_present_pct | 99.7 |
| duration_s | 248.4 |
| frames | 7314 |

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
