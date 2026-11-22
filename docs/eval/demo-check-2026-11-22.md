# Demo check, live, both seats (2026-11-22)

- GO 10/21; scripts/demo_check.py, judged on the published PerceptionFrames; nothing recorded

| item | signal | verdict | details |
|---|---|---|---|
| AS2 | eyes: closures, blinks, squint / smile | **NO-GO** | 2 s closures, closed_ms continuous (+-100 ms): 1803.0 ms, 2204.0 ms, 3662.0 ms; blinks 9/10: 8/10; squint / smile reported closed: 0: 6/6 windows with a closure |
| AS3 | yawn | GO | yawns 3/3: 3/3 |
| AS4 | fatigue nod | GO | slow head drop with closed eyes >= 4/5: 4/5 |
| R-FL3 | faces big enough: before and during the run | **NO-GO** | both faces >= min_face_width_px (framing): driver 250 px, passenger 250 px (need 250); driver face >= 250 px during the run (>= 90 % of frames): median 250.0 px, 57% of the frames big enough; passenger face >= 250 px during the run (>= 90 % of frames): median 250 px, 97% of the frames big enough |
| AS5 | gaze zones (calibrated) | **NO-GO** | calibration owl >= 95 %, lizard >= 90 %, head turned in every OWL step: done, owl 0.5064, lizard 0.5034, no head turn: ['mirror_left', 'mirror_right', 'mirror_rear', 'cluster', 'infotainment', 'lap', 'passenger'], warnings 9; zone road while looking at the road >= 70 %: calibrated True, road 0%; left mirror seen >= 8/10 and without off_road x10: 2/10 clean, mirror_left seen 3/10; >= 3 glances at the passenger: 0 glances |
| AS6 | VATS + entropy | GO | gaze entropy falls (30 s fixed): 2.39 -> 1.793 |
| AS7 | driver phone | GO | driver phone < 1 s: 0.08 s, source detector, key True; phone NOT the driver's: driver phone in_use frames 0 |
| AS8 | head yes / no | GO | head yes driver: answers ['yes'] |
| AS9 | gestures driver | **NO-GO** | Thumb_Up driver: gestures ['Thumb_Up']; Open_Palm driver: gestures []; Thumb_Up driver (reminder): gestures ['Thumb_Up'] |
| AS10 | identity driver | GO | identity sofer < 3 s: 0.0 s, andrei |
| AS11 | driver speaking | GO | driver speaking: onset 0.0 s after the prompt, held 89% |
| AS12 | driver camera covered | GO | covered -> monitoring_ok=false < 2 s: 1.93 s, blurred |
| AS13 | rear-seat glance | off (demo.rear_seat) | frame keeps the defaults |
| AP1 | passenger present + identity | **NO-GO** | identity pasager < 3 s: None s, None |
| AP2 | passenger asleep / awake | **NO-GO** | passenger asleep < 10 s: None s; passenger awake again: 0.0 s |
| AP3 | passenger speaking | GO | passenger speaking: onset 1.3 s after the prompt, held 100% |
| AP4 | passenger phone | **NO-GO** | passenger.holding_phone: 0% of frames |
| AP5 | passenger camera covered | **NO-GO** | passenger covered -> monitoring_ok=false: None s after the prompt, None |
| AP6 | passenger gestures / answer | **NO-GO** | head yes passenger: answers ['yes']; Thumb_Up passenger: gestures []; Open_Palm passenger: gestures [] |
| J1 | driver face >= 20 fps, both cameras | GO | driver face >= 20 fps (both cameras): process 30.2 fps (min 16.2), capture 30.2 fps |
| N | 60 s normal driving, zero false events | **NO-GO** | 60 s normal driving: zero false events: {'driver closure': 8, 'driver nod': 3} |
