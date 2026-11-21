# Phone detector comparison, driver camera (2026-11-21)

- capture 1920x1080, processed at 1280x720 (as the runtime); frames per position: ear 92, chest 93, lap 96, side 87, none 93, wallet 93
- threshold per variant = lowest one with **zero** false frames on `none` + `wallet` (min 0.25)
- detection % = frames with a phone box at that threshold (the runtime adds the 3-of-5 vote on top)

| variant | ms p50 / p95 | max false conf | threshold | ear % | chest % | lap % | side % | mean % |
|---|---|---|---|---|---|---|---|---|
| yolo26n@416 | 14.3 / 17.2 | 0.00 | 0.25 | 3 | 99 | 0 | 76 | 45 |
| yolo26n@640 | 23.1 / 28.1 | 0.51 | 0.53 | 1 | 45 | 0 | 59 | 26 |
| yolo26s@640 | 63.3 / 71.9 | 0.46 | 0.48 | 58 | 100 | 54 | 100 | 78 |

**Choice: yolo26n@416, conf_min 0.25** (best mean detection with p95 <= 60 ms).
