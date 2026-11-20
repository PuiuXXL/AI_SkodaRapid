# P3: LLM + voce + telefon

> Citește întâi `DriveMate-PLAN-FINAL.md`: secțiunile 4.D, 4.E, 4.F, 4.K, 5, 6, 7 și 13. Fișierul ăsta îți spune ce faci, în ce ordine, cum și ce ai voie să atingi.

## Misiunea ta

Tot ce spune și aude asistentul, plus telefonul șoferului. Tu faci ca DriveMate să pară un copilot, nu un senzor. Asistentul tău:
- vorbește scurt și știe când să tacă;
- înțelege un „da” spus în orice fel;
- citește mesajele, ca șoferul să nu atingă telefonul.

**Tu propui și formulezi. Când are voie asistentul să vorbească și ce e sigur decide P2.**

---

## Unde lucrezi

- `assistant/**`: `config/assistant.yaml`, `data/**`, `prompts/**` și restul
- `integrations/phone_bridge.py`, `integrations/audio_clips.py`
- `dashboard/src/voice/**`, `dashboard/public/sounds/**`
- `tests/assistant/**`, `docs/assistant.md`, `requirements/p3-assistant.txt`

Dacă ai nevoie de o schimbare în altă parte (un eveniment sau un câmp nou în contract, un șablon, un POI în `stops.json`), anunță pe grup, ca să nu lucrați doi oameni în același fișier în același timp.

---

## Interfețele tale

| Ce | Direcție | Format |
|---|---|---|
| `assistant/client.py`: `async def handle_event(event, state) -> list[Action]` | core te apelează (în același proces) | modelele Pydantic din `shared/contracts.py`; timeout 2,5 s → `fallback.py` |
| `assistant/refusal.py`: `def is_refusal(text) -> bool` | core te apelează | cuvinte-cheie, determinist, sub 1 ms |
| `assistant/router.py` | core îl montează | `/tts/{id}.mp3` (edge-tts, propoziție cu propoziție) |
| Vocea din browser (`dashboard/src/voice/`) | ↔ `/ws/ui` | **primești** `speak`, `speak_control`, `alarm`, `media`; **trimiți** `speech`, `speech_onset`, `speak_done`, `alarm_played` |
| API-ul vocii pentru UI-ul lui P4 | `dashboard/src/voice/index.*` | exporți, de exemplu, `initVoice(ws)`, `onTranscript(cb)`, `isSpeaking()`. Așa vocea ta și UI-ul lui P4 rămân separate |
| Puntea cu telefonul (proces separat) | ↔ `/ws/phone` | **trimiți** `phone_message`, `call`, `phone_status`; **primești** `send_reply`, `send_sms` |

---

## Pașii, în ordine

### 1. În seara asta, până la 02:00: trei teste critice
- **Vocea:**
  - în **Google Chrome** (nu Chromium): `webkitSpeechRecognition`, cu `lang = "ro-RO"`, `continuous = true`, `interimResults = true` și repornire în `onend`;
  - edge-tts, cu vocile `ro-RO-AlinaNeural` / `ro-RO-EmilNeural`;
  - **după test decideți limba**: română sau, ca rezervă, engleză.
- **KDE Connect:**
  - aplicația pe un **Android**, iar pe laptop pachetul `kde-connect` (`sudo dnf install kde-connect`);
  - le împerechezi și deschizi firewall-ul (`sudo firewall-cmd --add-service=kdeconnect`).

  Ce verifici:
  1. `kdeconnect-cli -l` vede telefonul;
  2. `kdeconnect-cli -d <id> --send-sms "test" --destination +40…` trimite SMS-ul;
  3. o notificare de WhatsApp apare pe D-Bus (`busctl --user tree org.kde.kdeconnect`);
  4. răspunsul trimis din notificare (metoda `sendReply` a obiectului notificării) ajunge pe WhatsApp.

  Dacă WiFi-ul din sală izolează dispozitivele, folosești hotspot-ul telefonului sau tethering prin USB.
- **LLM:** primul apel cu ieșire JSON structurată, validat cu modelele `Action` din contract.

### 2. Clientul LLM (`assistant/`)
- **`summary.py`** transformă starea în ~10 rânduri: nivelul de siguranță, F, D, cauza, cabina, mesajele, mementourile și ultimele 3 replici.
- **`prompts/system.md`** conține:
  - rolul asistentului;
  - regulile de formă: maximum 15 cuvinte către șofer, nimic de citit, nimic în timpul manevrelor;
  - lista de acțiuni;
  - câteva exemple.
- **`client.py`:**
  - răspunsul vine în streaming, iar prima propoziție merge imediat la TTS;
  - maximum 3 acțiuni pe răspuns;
  - după 2,5 s fără răspuns trece pe `fallback.py`, care are texte fixe pentru fiecare tip de eveniment.
- **`policies.py`:**
  - cel mult o intervenție proactivă la 30 s;
  - **nicio inițiativă cât timp `assistant.muted_until` e în viitor**.

### 3. Vocea în browser (`dashboard/src/voice/`)
- **Recunoașterea vocală e continuă și half-duplex:** o oprești cât timp vorbește asistentul.
- **Momentul exact în care începe vorbirea:** un flux `getUserMedia` separat, cu un `AnalyserNode` (WebAudio), trimite `speech_onset`. P2 îl folosește pentru reacția verbală.
- **Fereastra de dialog:** core-ul o deschide când îi trimiți `speak_done` pentru o întrebare. Cât e deschisă, accepți vocea fără numele asistentului (6 s).
- **Player-ul:**
  - redă propoziție cu propoziție;
  - la `speak_control` face pause/resume/stop (D4: „...cum ziceam”);
  - dă muzica mai încet cât vorbește asistentul;
  - **alarma întrerupe orice**.
- **Răspunsul da/nu (E3):** combini vocea ta cu `head.answer` și `gesture` din stare.

### 4. Clipurile (`integrations/audio_clips.py`)
- Le generezi cu edge-tts în `dashboard/public/sounds/clips/`:
  - alarma cu numele fiecărui profil;
  - „Ești bine?”;
  - instrucțiunile pentru pasager;
  - **„Ok, te las în pace.”**;
  - **„Îi dau de veste lui {contact}.”**;
  - confirmările scurte.

### 5. Puntea cu telefonul (`integrations/phone_bridge.py`, proces separat)
- Cu `dbus-next` asculți semnalul de notificare nouă de la dispozitivul KDE Connect. Din notificare citești aplicația, titlul (expeditorul), textul și dacă se poate răspunde la ea.
- **Lista albă** de aplicații și contacte stă în `assistant/config/assistant.yaml`.
- **Comenzile:**
  - `send_reply` → metoda de răspuns a notificării (WhatsApp);
  - `send_sms` → `kdeconnect-cli --send-sms` (SMS și mesajul către contactul de încredere).
- Puntea poate rula și pe alt laptop cu Linux: adresa core-ului o ia din `.env` (`CORE_URL`).

### 6. Remediile
- **Cauza (D2):** delegarea către pasager („Maria, poți să-i povestești tu?”) și „Lasă telefonul, ți-l citesc eu.”
- **Muzica (D8):**
  - logica în `assistant/music.py`, catalogul în `assistant/data/media_catalog.json`;
  - ~20 de piese fără drepturi de autor, etichetate cu gen, energie 1–5 și `kid_safe`;
  - fișierele mp3 le dați între voi, nu prin git.
- **Oboseala (D3 + D10):** conversația care îl ține treaz pe șofer, inclusiv întrebarea KSS 1–9.
- **Refuzul (D10):**
  - **`is_refusal(text)`** recunoaște „lasă-mă în pace”, „taci”, „nu acum”, „nu vreau”, „lasă”, cu și fără diacritice;
  - dacă LLM-ul înțelege un refuz mai subtil, întoarce `stay_silent` cu `reason="driver_refused"`;
  - **dacă se anunță contactul decide regula C10 a lui P2, nu tu.**
- **Mementourile (K1, D9):** `create_reminder`, cu o categorie din `stops.json`, urmat de confirmare.
- **Mesajele (F3, F8):**
  - reformulezi răspunsul scurt și adaugi ETA;
  - ceri confirmare, apoi îl trimiți prin punte;
  - citești răspunsul contactului de încredere când P2 îți dă voie (F2).

---

## Cum lucrezi fără ceilalți

- Stările din `tests/assistant/fixtures/*.json` (pornite de la exemplul din contract) → apelezi `handle_event` direct.
- Rulezi core-ul real cu `scripts/fake_perception.py`.
- Vocea o testezi pe o pagină simplă, `dashboard/src/voice/dev.html`.
- Testele din `tests/assistant/`: `is_refusal` pe ~30 de fraze, validarea acțiunilor și rezerva la timeout.

## Calendar

| Când | Ce |
|---|---|
| 02:00 | STT/TTS în română (sau decizia pentru engleză); KDE Connect: citire + răspuns + SMS; primul apel LLM |
| Sâmbătă 12:00 | eveniment → LLM → voce în browser; notificare de pe telefon → citită cu voce |
| Sâmbătă 22:00 | tot ce e M din D, E, F (părțile tale) și K1 |
| Duminică | ajustezi promptul și textele după repetiții |

## Reguli comune (pe scurt; detaliile sunt în secțiunea 13 din plan)

- **Ramura ta:** `p3-assistant`. Faci commit pe fiecare funcție, cu mesaj în engleză și prefixul modulului: `assistant: add refusal detection`.
- **Înainte de fiecare punct de control:** `git fetch origin && git merge origin/main`, testele, `git push`. La merge în `main` ești al treilea (P2 → P1 → P3 → P4).
- **Eveniment, câmp sau șablon nou?** Anunți pe grup (`CONTRACT: …`). Câmpurile noi sunt opționale, cu valoare implicită.
- **Cheile, numerele de telefon și ID-ul KDE Connect** stau doar în `.env`. **Claude nu face commit sau push.**

## Blocul pentru `CLAUDE.local.md`

```
Lucrez ca P3 (LLM + voce + telefon) în proiectul DriveMate.
Citește roluri/P3-llm-voce-telefon.md și secțiunile 4.D, 4.E, 4.F, 6, 7, 13 din DriveMate-PLAN-FINAL.md.
Lucrez în principal în: assistant/**, integrations/phone_bridge.py, integrations/audio_clips.py,
dashboard/src/voice/**, dashboard/public/sounds/**, tests/assistant/**, docs/assistant.md,
requirements/p3-assistant.txt.
Dacă trebuie modificat ceva în afara lor (de ex. shared/contracts.py), spune-mi înainte, ca să anunț echipa.
LLM-ul întoarce doar acțiuni din lista din secțiunea 6; deciziile de siguranță și contactul de încredere sunt ale lui P2.
Texte către șofer: maximum 15 cuvinte, nimic de citit.
Nu face niciodată commit sau push.
```
