# Face Landmarker min_tracking_conf (R-FL2), 2026-11-21

Camera 1280x720 @ 30 fps. Three Face Landmarker instances on the **same live frames**, differing only in `min_tracking_conf`. Phases: 10 s still, 10 s fast head movements, 5 s head turned far.

- *jitter*: std of eye corners (33, 263) and nose tip (1) in the still phase, % of face width (lower = steadier)
- *redetections*: face lost then found again; *jumps*: nose moves > 15% of the face width between frames
- *score* = redetections + jumps + 0.1 x lost frames (fast + turned phases); lower is better

| min_tracking_conf | jitter_still_pct_face_width | lost_frames_fast_turned | redetections_fast_turned | jumps_fast_turned | frames_fast_turned | lost_still | ms_p50 | score |
|---|---|---|---|---|---|---|---|---|
| 0.5 | 37.668 | 0 | 0 | 0 | 406 | 0 | 7.44 | 0.0 |
| 0.6 | 37.668 | 0 | 0 | 0 | 406 | 0 | 7.27 | 0.0 |
| 0.7 | 37.668 | 0 | 0 | 0 | 406 | 0 | 7.41 | 0.0 |

**Proposed:** `face.min_tracking_conf: 0.5` (current yaml: 0.6).
