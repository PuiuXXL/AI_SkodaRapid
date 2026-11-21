# P2: context + siguranță + SOS (core)

> Citește întâi `DriveMate-PLAN-FINAL.md`: secțiunile 4.B, 4.C, 4.F, 4.G, 4.K, 5, 6, 7 și 13. Fișierul ăsta îți spune ce faci, în ce ordine, cum și ce ai voie să atingi.

## Misiunea ta

Ești creierul și frâna sistemului:
- primești ce vede P1 și ce face simulatorul;
- calculezi starea: reacția, F, D, atenția, riscul, cauza;
- decizi **prin reguli** ce se întâmplă și când are voie LLM-ul să vorbească.

Tot tu scrii **contractul**. În seara asta toată lumea depinde de tine: până la 00:30, contractul v2 trebuie să fie în `main`.

---

## Unde lucrezi

- `core/**`, inclusiv `core/main.py`, `core/config/thresholds.yaml` și `core/config/templates.yaml`
- `shared/contracts.py` (îl scrii tu în seara asta)
- `integrations/twilio_call.py`
- `scripts/fake_perception.py`
- `tests/core/**`, `docs/core.md`, `requirements/p2-core.txt`

## Modulele celorlalți (le folosești prin interfețe)

| Modul | Cine îl face | Cum îl folosești |
|---|---|---|
| `perception/**` | P1 | primești `PerceptionFrame` pe `/ws/perception` |
| `assistant/**`, `integrations/phone_bridge.py`, `integrations/audio_clips.py`, `dashboard/src/voice/**` | P3 | `assistant.handle_event(...)`, `assistant.refusal.is_refusal(...)`, `assistant.router`; puntea pe `/ws/phone` |
| `dashboard/**`, `simulator/**`, `integrations/contact_app/**`, `profiles/**`, fișierele din rădăcină | P4 | `simulator.Simulator`, `contact_app.router` și funcțiile `push_*`; citești `profile.json` |

---

## Interfețele (tu le definești în `shared/contracts.py`)

| Interfață | Direcție | Ce |
|---|---|---|
| `/ws/perception` | P1 → core; core → P1 | `PerceptionFrame` (15 Hz); comenzi `dialog_window`, `calibrate`, `debug`, `enroll` |
| `/ws/ui` | core ↔ browser (UI-ul lui P4 + vocea lui P3) | spre browser: `state` (10 Hz), `event`, `speak`, `speak_control` (pause/resume/stop), `alarm`, `media`. De la browser: `command` (regizorul), `speech` (text + timp), `speech_onset`, `speak_done`, `alarm_played` |
| `/ws/phone` | puntea lui P3 ↔ core | `phone_message`, `call`, `phone_status` / `send_reply`, `send_sms` |
| `assistant.handle_event(event, state) -> list[Action]` | core → P3, în același proces | apelul spre LLM. **Tu validezi fiecare acțiune** |
| `assistant.refusal.is_refusal(text) -> bool` | core → P3 | refuzul din dialogul de oboseală |
| `assistant.router` | P3, montat de tine | `/tts/{id}.mp3` |
| `integrations.contact_app` | P4, montat de tine | `router`, `push_status(state)`, `push_safe_contact(info)`, `push_sos(report)`; mesajele din pagină ajung la tine |
| `simulator.Simulator` | core → P4 | `tick() -> Trip`, `command(cmd)` |
| `integrations.twilio_call.place_sos_call(report) -> bool` | al tău | apelul SOS |

---

## Pașii, în ordine

### 1. În seara asta, până la 00:30: contractul v2
- **`shared/contracts.py`** (Pydantic v2) conține:
  - `PerceptionFrame`;
  - `State`, exact ca în secțiunea 7;
  - `Event`;
  - `Action`, cu câte un model pentru fiecare tip din secțiunea 6;
  - mesajele de pe WebSocket: `UiMessage`, `PerceptionCommand`, `PhoneEvent`, `PhoneCommand`;
  - `CONTRACT_VERSION = "2.0"`.
- **Toate câmpurile au valori implicite**, ca fiecare modul să poată trimite doar ce are.
- **`tests/core/fixtures/state_example.json`** e exemplul din plan, plus un test care îl validează cu `State`.
- **`core/config/thresholds.yaml`** are toate cheile:
  - pragurile de alarmă;
  - ponderile pentru F și D;
  - ferestrele de timp;
  - `refusal_mute_min`;
  - `safe_contact.fatigue_min` și `safe_contact.cooldown_min`;
  - `sos.countdown_s`;
  - `demo_mode`, pentru ferestre scurte în demo.
- **`core/config/templates.yaml`** conține șabloanele: raportul SOS, SMS-ul către contactul de încredere, mementoul de la oprire.
- **`scripts/fake_perception.py`** trimite `PerceptionFrame` pe `/ws/perception`, cu câte o tastă pentru fiecare situație din scenariu:

  | Tastă | Situație |
  |---|---|
  | `1` | normal |
  | `2` | privire în oglindă |
  | `3` | telefon |
  | `4` | privire spre pasager ×3 + pasagerul cu telefon |
  | `5` | privire fixă + reacții lente |
  | `6` | căscat + clipit lent + pasager adormit |
  | `7` | ochi închiși |
  | `8` | capul căzut / nu răspunde |
  | `9` | cameră acoperită |
  | `y` / `n` | răspuns din cap |
  | `h` | ✋ |

- Când e gata, faci merge în `main` și anunți pe grup: **„CONTRACT v2.0 în main”**.

### 2. În seara asta, în paralel: testul Twilio
- Dai un apel spre un număr românesc, cu un `<Say>` în română. Mesajul se citește din `templates.yaml`, numerele din `.env`.
- Dacă pe contul de probă apare mesajul Twilio sau se cere o tastă înainte, contul trece pe plată.
- Activezi permisiunile geografice pentru România.

### 3. Bucla core și siguranța
- **`core/main.py`:** FastAPI, plus bucla de stare la 10 Hz (asyncio). La fiecare pas combină ultimul `PerceptionFrame`, `simulator.tick()` și scorurile, construiește `State` și îl trimite pe `/ws/ui`.
- **`core/safety/arbiter.py`:** ordinea P0 > P1 > P2 > P3 > P4. Un nivel mai sus întrerupe tot ce e sub el: trimiți `speak_control: stop` și `media: stop`.
- **`core/safety/escalation.py`:** semnal discret → voce → alarmă.
  - Semnalul discret = `event: visual_cue`, pe care UI-ul lui P4 îl afișează.
  - Alarma = mesajul `alarm`, cu clipul care conține numele șoferului.
  - `alarm_ms` = timpul de la depășirea pragului până la `alarm_played` venit din browser.
- **`core/safety/monitoring.py`:** „Nu te mai văd”.
- **`core/safety/sos.py`:** mașina de stări pentru șoferul care nu răspunde:
  ```
  normal → alarm → asking („Ești bine?”) → countdown → sos_sent
  ```
  - Anularea vine pe orice canal: voce, cap, 👍.
  - La SOS, în ordine:
    1. clipurile cu instrucțiuni pentru pasager;
    2. `place_sos_call(report)`;
    3. `send_sms` prin puntea lui P3;
    4. `push_sos(report)` spre pagina lui P4.
- **Validatorul de acțiuni (C8):** fiecare acțiune a LLM-ului e verificată față de nivelul curent, de tabelul din secțiunea 6 și de `assistant.muted_until`. Acțiunile respinse ajung în jurnal.

### 4. Scorurile (`core/scoring/`)
- **`reaction.py`**, cu trei cronometre:
  - **vizual:** de la `visual_cue` până când `gaze.zone == road`;
  - **verbal:** de la `speak_done` (al unei întrebări) până la `speech_onset`;
  - **gest:** de la propunere până la `gesture` / `head.answer`.

  Referința e mediana primelor 3–5 reacții.
- **Restul scorurilor:**
  - `fatigue.py` (F);
  - `disengagement.py` (D), care contează doar cu F mic și context monoton;
  - `attention.py`;
  - `risk.py`, cu factorul de viteză;
  - `conversation.py`: buzele din ambele camere alternează și microfonul are nivel.
- **Metrii orbi** (B6) și **pragul simplu rulat în paralel** (`ab_baseline.py`).
- **Fereastra de dialog:** o deschizi când primești `speak_done` pentru o acțiune `ask`. Atunci trimiți `dialog_window` la P1 și pui `interaction.dialog_window_open = true`.

### 5. Cauza, mesajele, mementourile, fișa călătoriei
- **`cause.py`:** dacă zona `passenger` apare de cel puțin 3 ori în 30 s **și** `passenger.holding_phone` e adevărat → `passenger_showing_phone`. Celelalte etichete se calculează la fel.
- **`messages_timing.py`** (regula F2): amână, întreabă sau citește.
- **`reminders.py`:**
  - **K2:** viteza ajunge la 0 lângă un POI din aceeași categorie → `event: reminder_due`, cu șablonul din `templates.yaml`;
  - **K3:** oprirea propusă la oboseală e cea mai apropiată care rezolvă și un memento deschis.
- **`intervention.py`** (efectul fiecărei intervenții, înainte vs. după) și **`scorecard.py`** (J2, J3).

### 6. Contactul de încredere (C10): `core/safe_contact.py`
```
dialogul de oboseală e activ ȘI F ≥ safe_contact.fatigue_min
ȘI refuz: assistant.refusal.is_refusal(text) / ✋ / 👎 / LLM → stay_silent(reason="driver_refused")
  → event driver_refused
  → speak: clipul „Ok, te las în pace.” (+ „Îi dau de veste lui {contact}.” dacă announce = true)
  → assistant.muted_until = acum + refusal_mute_min        (P3–P4 tac; P0–P2 NU)
  → dacă profile.safe_contact există ȘI consent = true ȘI a trecut cooldown_min:
       send_sms(SAFE_CONTACT_NUMBER din .env, șablonul din templates.yaml)
       push_safe_contact(...)                               (notificarea galbenă din pagină)
       safe_contact.notified_ts = acum; eveniment în jurnal (sursa: REGULĂ)
```
- Răspunsul contactului vine ca un mesaj obișnuit și trece prin F2. După ce e citit, asistentul are voie **o singură dată** să propună oprirea, chiar dacă e pe liniște.

### Adăugat de P3: YouTube la cerere (D11, prioritate S, v2.2)
P3 a implementat căutarea și redarea de pe YouTube (ramura `p3-youtube-media`, `docs/assistant.md` §6.1). În partea ta rămân doar câteva lucruri mici, de făcut când scrii core-ul:
- **Contractul** (`shared/contracts.py`), toate câmpurile opționale: `ActionType` + `"search_media"`; `Action` + `query`, `kind` (`music` / `podcast`), `options` (listă de dict-uri), `title`; `ask.expects` + `"choice"`; `media.source` (`"catalog"` / `"youtube"`). Copia provizorie a lui P3 le are deja. Copiază-le de acolo.
- **Validatorul C8:** `search_media` nu ajunge niciodată la core (asistentul o rezolvă intern). Dacă totuși apare, o respingi. Accepți `ask` cu `expects: "choice"` (nivel P3/P4, ca orice `ask`) și `play_media` cu `track_id: "yt:<id>"` (doar P4, ca orice muzică).
- **Executarea `play_media`:** `{"type": "media", "action": "play", "url": music.track_url(track_id), "volume": …, "loop": music.loops(track_id)}`. Pui `state.media.title = action.title` și `state.media.source`. Alarmele și arbitrul opresc muzica la fel ca acum.
- **`handle_event` poate dura mai mult** pentru o căutare (LLM + căutare, ~2–8 s). Rulează-l mereu ca task separat, niciodată în bucla de 10 Hz (oricum așa trebuie). Spune „Caut.” imediat prin `on_early_speech`.
- **DialogManager:** răspunsurile la alegere („a doua”, 👍, „altceva”) trec prin același `dialog.handle(...)`. Dacă întoarce `handled=False`, textul e o cerere nouă → `driver_speech`. Evenimentele din `result.events` (inclusiv `driver_speech` pentru „da, ceva metal” la oferta de muzică) se trimit la `handle_event`, ca acum.
- **Warm-up la pornire** (plan §8, regula 5): `asyncio.create_task(assistant.media_search.warm_up())`.
- **Eficiența intervenției (D6):** muzica pornită la cerere are `reason="driver_request"`. Doar cea pornită pentru D (`reason="disengagement"`) intră în măsurarea efectului.

---

## Cum lucrezi fără ceilalți

- `scripts/fake_perception.py` ține locul lui P1.
- `core/dev/fake_assistant.py` întoarce acțiuni fixe până e gata P3.
- Simulatorul fals: o funcție care întoarce un `Trip` constant, până e gata P4.
- Testele stau în `tests/core/`: le dai stări JSON și verifici nivelul de siguranță, alarma, SOS-ul, regula C10 și cooldown-ul.

## Calendar

| Când | Ce |
|---|---|
| 00:30 | contractul v2 în `main` + `thresholds.yaml` + `templates.yaml` + `fake_perception.py` |
| 02:00 | testul Twilio |
| Sâmbătă 12:00 | ochi închiși → alarmă în browser în sub 300 ms; starea live pe `/ws/ui` |
| Sâmbătă 22:00 | tot ce e M: SOS, scorurile, cauza, mesajele, mementourile, C10, A/B, fișa |
| Duminică | reglezi `thresholds.yaml` în sală |

## Reguli comune (pe scurt; detaliile sunt în secțiunea 13 din plan)

- **Ramura ta:** `p2-core`. Faci commit pe fiecare funcție, cu mesaj în engleză și prefixul modulului: `core: add SOS countdown`.
- **La punctul de control ești primul care face merge în `main`** (ordinea e P2 → P1 → P3 → P4).
- **Modificările de contract** le faci imediat în `main` și le anunți. Câmpurile noi sunt opționale, cu valoare implicită, și nu redenumești și nu ștergi nimic până duminică.
- **Cheile și numerele de telefon** stau doar în `.env`. **Claude nu face commit sau push.**

## Blocul pentru `CLAUDE.local.md`

```
Lucrez ca P2 (context + siguranță + SOS) în proiectul DriveMate.
Citește roluri/P2-context-siguranta.md și secțiunile 4.B, 4.C, 5, 6, 7, 13 din DriveMate-PLAN-FINAL.md.
Lucrez în principal în: core/**, shared/**, integrations/twilio_call.py, scripts/fake_perception.py,
tests/core/**, docs/core.md, requirements/p2-core.txt.
Dacă trebuie modificat ceva în afara lor, spune-mi înainte, ca să anunț echipa.
Regulile de siguranță (P0–P2), SOS-ul și contactul de încredere sunt deterministe: fără LLM pe calea lor.
Câmpurile noi din contract sunt opționale, cu valoare implicită; nu redenumi și nu șterge câmpuri.
Pragurile stau în core/config/thresholds.yaml, șabloanele în core/config/templates.yaml.
Nu face niciodată commit sau push.
```
