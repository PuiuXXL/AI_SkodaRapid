# Eye / head / mouth evaluation: laptop-closures (2026-11-21)

- **mode:** replay of a labelled session
- **session:** 20261121-145034_eval-laptop-closures
- **frames:** 1554

## Exit criteria

| Criterion | Result |
|---|---|
| blinks detected >= 95% | not measured |
| false closures <= 1 per minute | **FAIL** |
| 2 s closures detected 100%, closed_ms error < 100 ms | **FAIL** |
| eyes closed -> reported CLOSED, median < 300 ms (plan §8 alarm budget) | PASS |
| head drop with closed eyes reported as nodding in every nod window | **FAIL** |
| squint / smile reported as closed: 0 | not measured |
| yawns detected >= 90% | not measured |
| no yawn while speaking | not measured |
| speaking detected in >= 90% of segments (< 1 s after the lips start moving) | not measured |
| angle jitter < 1 deg with the head still | not measured |
| face_too_small shown when stepping back | not measured |

## Metrics

| Metric | Value |
|---|---|
| closures_labelled | 4 |
| closures_detected | 4 |
| closed_ms_error_mean | 624.6 |
| closed_ms_error_max | 827.9 |
| closed_detect_latency_ms_median | 53.3 |
| closed_detect_latency_ms_max | 109.5 |
| nods_labelled | 2 |
| nods_detected | 0 |
| false_closures | 1 |
| false_closures_per_min | 1.07 |
| blinks_spontaneous | 7 |
| face_width_px_median | 348.1 |
| face_present_pct | 97.4 |
| duration_s | 56.3 |
| frames | 1554 |

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

## Notes

Short re-run (`eval_eyes.py --only eyes_closed nod`). Evaluated with the eye-state CNN off: recorded live with it on,
it vetoed all 4 closures (it read the shut eyes as open); with it off 4/4 are detected, latency median 53 ms. The
duration error and the nod misses are explained in `eyes-laptop-cnn-2026-11-21.md` (Diagnosis).
