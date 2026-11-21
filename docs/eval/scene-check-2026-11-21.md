# Scene check, live, both seats (2026-11-21)

- scenes run: S1 S2 S3 S4 S5 S6 S8 S9 N; criteria passed 14/24
- driver: Logi C615 (1080p30 capture, 720p processing); passenger: LifeCam HD-6000 (720p30, 10 Hz)
- judged on the PerceptionFrames P1 publishes (scripts/scene_check.py); nothing recorded

| scene | criterion | result | detail |
|---|---|---|---|
| S1 | identity sofer < 3 s | PASS | 0.0 s, andrei |
| S1 | identity pasager < 3 s | PASS | 0.0 s, cristian |
| S1 | head yes driver | **FAIL** | answers [] |
| S1 | head yes passenger | **FAIL** | answers [] |
| S2 | left mirror without off_road x10 | **FAIL** | 2/10 clean, mirror_left seen 4/10 |
| S2 | covered -> monitoring_ok=false < 2 s | **FAIL** | 3.53 s, face_lost |
| S3 | driver phone < 1 s | PASS | 0.03 s, source detector, key True |
| S3 | Thumb_Up driver | PASS | gestures ['Thumb_Up'] |
| S3 | Thumb_Up passenger | PASS | gestures ['Thumb_Up'] |
| S4 | >= 3 glances at the passenger | **FAIL** | 0 glances |
| S4 | passenger.holding_phone | PASS | 54% of frames |
| S4 | phone NOT the driver's | PASS | driver phone in_use frames 0 |
| S5 | gaze entropy falls (30 s fixed) | PASS | 2.168 -> 1.188 |
| S6 | yawns 3/3 | PASS | 3/3 |
| S6 | Open_Palm driver | PASS | gestures ['Open_Palm'] |
| S6 | Open_Palm passenger | **FAIL** | gestures [] |
| S6 | passenger asleep < 12 s | **FAIL** | None s |
| S9 | passenger awake again | PASS | 0.0 s |
| S8 | 2 s closures, closed_ms continuous (+-100 ms) | PASS | 2132.0 ms, 2018.0 ms, 2661.0 ms |
| S8 | blinks 9/10 | PASS | 10/10 |
| S8 | squint / smile reported closed: 0 | **FAIL** | 3/6 windows with a closure |
| S9 | slow head drop with closed eyes 5/5 | **FAIL** | 1/5 |
| N | 60 s normal driving: zero false events | **FAIL** | {'passenger posture': 4} |
| perf | driver face >= 20 fps (both cameras) | PASS | process 29.1 fps (min 11.4), capture 30.1 fps |
