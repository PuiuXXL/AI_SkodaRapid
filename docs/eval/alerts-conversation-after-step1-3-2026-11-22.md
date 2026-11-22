# Alerts vs. conversation: after-step1-3 (2026-11-22)

Core (P2 rules) + P3 assistant in fake time, `scripts/eval_alert_conversation.py`. LLM: `scripted` (answer after 1.0 s). Speed 100.0 km/h (off-road limit 1.5 s at >= 90 km/h, spoken warning +1 s, alarm +3 s). Driver turns: "Copilot, cât mai am până la destinație?" / "Și ce e de văzut pe drum?" / "Bine, mulțumesc.".

| Scenario | answers heard to the end | assistant cut mid-sentence | questions dropped | driver turns lost | 'look at the road' by P2 | ... by the LLM | cause events | P2 cues | alarms | speech queued behind speech | speech over an alarm |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `control` | 3/3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| `glance_1_0s` | 3/3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| `glance_1_8s` | 3/3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 0 |
| `glance_3_0s` | 2/3 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 2 | 0 |
| `glances_repeated` | 3/3 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 2 | 0 |
| `passenger_talk` | 3/3 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 0 |
| `microsleep` | 2/3 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 3 | 0 |

## Scenarios

### `control`: conversation, eyes on the road

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
 19.48s  driver        says 'Și ce e de văzut pe drum?'
 20.48s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 20.48s  assistant     <- speak? 'Te mai ajut cu ceva?'
 20.48s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 31.92s  driver        says 'Bine, mulțumesc.'
 31.94s  assistant     <- speak? 'Spune.'
```

### `glance_1_0s`: conversation + one 1.0 s glance at the infotainment during the answer

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        looks at infotainment for 1.0 s
 19.48s  driver        says 'Și ce e de văzut pe drum?'
 20.48s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 20.48s  assistant     <- speak? 'Te mai ajut cu ceva?'
 20.48s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 31.92s  driver        says 'Bine, mulțumesc.'
 31.94s  assistant     <- speak? 'Spune.'
```

### `glance_1_8s`: conversation + one 1.8 s glance (above 1.5 s at >= 90 km/h, before the voice stage)

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        looks at infotainment for 1.8 s
 10.60s  core          speak_control pause
 10.90s  core          speak_control resume
 20.56s  driver        says 'Și ce e de văzut pe drum?'
 21.56s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 21.56s  assistant     <- speak? 'Te mai ajut cu ceva?'
 21.56s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 33.00s  driver        says 'Bine, mulțumesc.'
 33.02s  assistant     <- speak? 'Spune.'
```

### `glance_3_0s`: conversation + one 3.0 s glance (P2's spoken warning)

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        looks at infotainment for 3.0 s
 10.60s  core          speak_control pause
 11.70s  core             pending question of the assistant DROPPED
 11.70s  core          speak_control stop
 11.70s  assistant        STOPPED mid-sentence: 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
 11.70s  P2:dis        <- speak 'Andrei, fii atent la drum, te rog.'
 15.48s  driver        says 'Și ce e de văzut pe drum?'
 16.48s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 16.48s  assistant     <- speak? 'Te mai ajut cu ceva?'
 16.48s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 27.92s  driver        says 'Bine, mulțumesc.'
 27.94s  assistant     <- speak? 'Spune.'
```

### `glances_repeated`: conversation + a 1.8 s glance every 7 s (4 times)

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        looks at infotainment for 1.8 s
 10.60s  core          speak_control pause
 10.90s  core          speak_control resume
 16.00s  driver        looks at infotainment for 1.8 s
 17.60s  core          speak_control pause
 17.90s  core          speak_control resume
 21.68s  driver        says 'Și ce e de văzut pe drum?'
 22.68s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 22.68s  assistant     <- speak? 'Te mai ajut cu ceva?'
 22.68s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 23.00s  driver        looks at infotainment for 1.8 s
 24.60s  core          speak_control pause
 24.90s  core          speak_control resume
 30.00s  driver        looks at infotainment for 1.8 s
 31.60s  core          speak_control pause
 31.90s  core          speak_control resume
 36.34s  driver        says 'Bine, mulțumesc.'
 36.36s  assistant     <- speak? 'Spune.'
```

### `passenger_talk`: conversation while Maria talks and the driver glances at her (4 x 0.8 s)

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        looks at passenger for 0.8 s
 13.00s  driver        looks at passenger for 0.8 s
 17.00s  driver        looks at passenger for 0.8 s
 19.48s  driver        says 'Și ce e de văzut pe drum?'
 20.48s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 20.48s  assistant     <- speak? 'Te mai ajut cu ceva?'
 20.48s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 21.00s  driver        looks at passenger for 0.8 s
 31.92s  driver        says 'Bine, mulțumesc.'
 31.94s  assistant     <- speak? 'Spune.'
 39.70s  -> assistant  event cause_detected {'label': 'passenger_talk'}
```

### `microsleep`: conversation + eyes closed 3.5 s during the answer, then 'Da, sunt bine'

```
  3.10s  assistant     <- speak 'Salut, Andrei și Maria! Drum bun.'
  3.10s  -> assistant  event trip_start
  6.64s  driver        says 'Copilot, cât mai am până la destinație?'
  7.64s  assistant     <- speak 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
  7.64s  assistant     <- speak? 'Te mai ajut cu ceva?'
  7.64s  -> assistant  event driver_speech {'text': 'Copilot, cât mai am până la destinație?'}
  9.00s  driver        eyes CLOSED
 11.00s  core             pending question of the assistant DROPPED
 11.00s  core          speak_control stop
 11.00s  assistant        STOPPED mid-sentence: 'Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează o porțiune liniștită de autostradă.'
 12.00s  core          speak_control stop
 12.00s  core          ALARM microsleep (P1)
 12.50s  driver        eyes open
 14.60s  P2:sos        <- speak? 'Ești bine?'
 17.10s  driver        says 'Da, sunt bine.'
 17.12s  P2:sos        <- speak 'Ok.'
 18.62s  driver        says 'Și ce e de văzut pe drum?'
 19.62s  assistant     <- speak 'Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu telecabină. Merită o pauză scurtă acolo.'
 19.62s  assistant     <- speak? 'Te mai ajut cu ceva?'
 19.62s  -> assistant  event driver_speech {'text': 'Și ce e de văzut pe drum?'}
 19.70s  P2:drw        <- speak? 'Andrei, facem o pauză?'
 32.88s  driver        says 'Bine, mulțumesc.'
 32.90s  assistant     <- speak? 'Spune.'
```

