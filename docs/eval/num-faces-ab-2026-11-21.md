# Face Landmarker num_faces 1 vs 2 (R-FL1), 2026-11-21

Camera 1280x720 @ 30 fps reported, 29.9 fps processed (both models on every frame). Two Face Landmarker instances on the **same live frames**, differing only in `num_faces`. 10 cued blinks. Width = time below 50 % of the raw EAR dip (interpolated); ref = p90 of EAR in the 2 s before the cue. Blink duration in humans is ~100-400 ms (Schiffman 2001; Caffier et al. 2003).

## Summary

```
n1: {'w50_ear_L_ms_median': 165.5, 'w50_ear_R_ms_median': 182.5, 'w50_eyeBlink_ms_median': 158.5, 'depth_L_median': 0.9, 'frames_with_face': 920, 'latency_ms_p50_p95': (8.28, 9.13)}
n2: {'w50_ear_L_ms_median': 160.5, 'w50_ear_R_ms_median': 178.0, 'w50_eyeBlink_ms_median': 161.0, 'depth_L_median': 0.9, 'frames_with_face': 916, 'latency_ms_p50_p95': (9.67, 10.8)}
```

## Per blink

| blink | n1_w50_L | n1_depth_L | n1_w50_R | n1_depth_R | n1_w50_eyeBlink | n2_w50_L | n2_depth_L | n2_w50_R | n2_depth_R | n2_w50_eyeBlink |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 355.0 | 0.893 | 548.0 | 0.883 | 335.0 | 450.0 | 0.841 | 477.0 | 0.865 | 364.0 |
| 2 | 169.0 | 0.806 | 184.0 | 0.861 | 158.0 | 160.0 | 0.816 | 179.0 | 0.87 | 156.0 |
| 3 | 156.0 | 0.875 | 144.0 | 0.843 | 158.0 | 173.0 | 0.847 | 180.0 | 0.823 | 168.0 |
| 4 | 170.0 | 0.873 | 181.0 | 0.716 | 179.0 | 161.0 | 0.918 | 165.0 | 0.871 | 168.0 |
| 5 | 162.0 | 0.922 | 188.0 | 0.84 | 159.0 | 158.0 | 0.908 | 191.0 | 0.887 | 160.0 |
| 6 | 186.0 | 0.85 | 207.0 | 0.832 | 175.0 | 177.0 | 0.886 | 177.0 | 0.891 | 172.0 |
| 7 | 157.0 | 0.859 | 177.0 | 0.783 | 150.0 | 142.0 | 0.897 | 147.0 | 0.86 | 138.0 |
| 8 | 134.0 | 0.825 | 161.0 | 0.77 | 134.0 | 121.0 | 0.828 | 148.0 | 0.836 | 124.0 |
| 9 | 156.0 | 0.811 | 173.0 | 0.725 | 150.0 | 138.0 | 0.809 | 160.0 | 0.77 | 138.0 |
| 10 | 179.0 | 0.866 | 197.0 | 0.77 | 172.0 | 166.0 | 0.899 | 190.0 | 0.845 | 162.0 |
