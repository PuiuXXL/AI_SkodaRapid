# P4: dashboard + simulator + DriveMate Contact + repo

> Citește întâi `DriveMate-PLAN-FINAL.md`: secțiunile 4.H, 4.I, 4.J, 4.F (F5, F8), 9, 12, 13 și 15. Fișierul ăsta îți spune ce faci, în ce ordine, cum și ce ai voie să atingi.

## Misiunea ta

Tot ce vede juriul trece prin tine:
- dashboard-ul;
- harta;
- panoul de performanță;
- fișa călătoriei;
- pagina DriveMate Contact.

Construiești și **panoul regizorului**: fără el, demo-ul nu se poate controla. Mai ești și **gazda repo-ului**: scheletul, fișierele din rădăcină, README-ul și prezentarea.

---

## Unde lucrezi

- `dashboard/**`. Vocea din `dashboard/src/voice/` și sunetele din `dashboard/public/sounds/` le face P3.
- `simulator/**` (`route.json`, `stops.json`, `simulator.py`, `director.py`, `replay.py`)
- `integrations/contact_app/**`, `integrations/__init__.py`
- `profiles/**`, adică `profile.json`. Fișierele `calibration.json` și `face.npy` le scrie codul lui P1 și sunt în `.gitignore`.
- `scripts/fake_core.py`, `tests/dashboard/**`, `tests/scenes/**`, `presentation/**`
- Din rădăcină: `README.md`, `run.sh`, `.env.example`, `.gitignore`, `requirements.txt`, `requirements/p4-dashboard.txt`
- Din `docs/`: tot, în afară de `perception.md`, `core.md` și `assistant.md`

Scheletul repo-ului, adică primul commit, creează toate folderele. Dacă după aceea ai nevoie de o schimbare în altă parte, anunță pe grup, ca să nu lucrați doi oameni în același fișier în același timp.

---

## Interfețele tale

| Ce | Direcție | Format |
|---|---|---|
| `/ws/ui` (core) | ↔ | **primești** `state` (10 Hz) + `event`; **trimiți** `command` (regizorul, tasta D, scenele) |
| Video de la P1 | → UI | `<img src="http://localhost:8001/video/driver">` și `/video/passenger` (MJPEG) |
| Vocea lui P3 | în browser | `import { initVoice } from "./voice"` |
| `simulator.Simulator` (al tău, apelat de core) | core → tu | `tick() -> Trip`, `command(cmd)`: salt la scenă, viteză, timp ×N, oprire la POI |
| `integrations/contact_app` (al tău, montat de core) | core → tu | `router`, `push_status(state)`, `push_safe_contact(info)`, `push_sos(report)`; mesajele din pagină → core |

---

## Pașii, în ordine

### 1. În seara asta, până la 02:00: scheletul, Contact și datele false
- **Scheletul repo-ului**, cu promptul pentru Claude Code, folosind contractul din secțiunea 7:
  - toate folderele din secțiunea 12;
  - `requirements/p1-perception.txt` … `p4-dashboard.txt`, iar `requirements.txt` doar le include cu `-r`;
  - `.env.example` cu toate cheile cunoscute, **fără valori reale**;
  - `.gitignore` cu: `CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.env`, modelele, `profiles/*/calibration.json`, `profiles/*/face.npy`, fișierele media, jurnalele, `roluri/` și planurile;
  - `run.sh`, care pornește core-ul, percepția, puntea și dashboard-ul. Cu `--fake`, pornește `fake_perception` în locul percepției.
- **Primul commit îl faci tu, ca om.** Îl împingi în `main`, apoi creezi cele 4 ramuri.
- **DriveMate Contact minimal + tunelul:** rulezi `cloudflared tunnel --url http://localhost:8000` și deschizi URL-ul de pe un telefon **pe date mobile**.
- **`scripts/fake_core.py`** trimite `state_example.json` pe un WebSocket local, cu valori care se mișcă. Așa lucrezi la UI fără core.

### 2. Dashboard-ul: întâi pe date false, apoi pe core
Componentele stau în `dashboard/src/components/`:
- **video ×2** (MJPEG); tasta D trimite `command: debug`;
- **graficul cu 3 linii** (atenție, oboseală, dezinteres), fără animații, cu ultimele ~120 de puncte;
- **jurnalul**: sursa REGULĂ/LLM, canalul, latența;
- **contorul A/B**;
- **ocupanții**;
- **mesajele, mementourile, starea telefonului** și „atingeri telefon: 0”;
- **semnalul discret**: o lumină sau un chenar colorat la `event: visual_cue`;
- **indicatorul de liniște**: „Asistentul tace până la {ora}”, când `assistant.muted_until` e setat.

### 3. Performanța (J1) și fișa călătoriei (J2, J3)
- **Panoul de performanță**, mereu vizibil:
  - fps pe fiecare cameră;
  - ms pe model, p50/p95;
  - latența cap-coadă;
  - **latența alarmei**, mare și colorată;
  - LLM, STT, TTS și timpul de la mesaj la voce;
  - CPU, RAM, GPU.
- **Fișa de la final:**
  - cel mai lung interval concentrat;
  - reacția față de referință;
  - metrii orbi;
  - mesajele gestionate fără mâini;
  - contorul A/B;
  - efectul intervențiilor;
  - mementourile rezolvate.

### 4. Simulatorul și harta
- **`simulator/route.json`:** o polilinie oraș → autostradă, cu viteza pe fiecare segment.
- **`simulator/stops.json`:** POI-uri cu `id`, `name`, `category`, `lat`, `lon`, `km`. Cel puțin o benzinărie (OMV) pe la km 42 și o cafenea.
- **`simulator.py`:**
  - `tick()` la 10 Hz;
  - timp accelerat;
  - oprire la POI (`stopped=true`, `at_poi`).
- **Harta Leaflet:** traseul, POI-urile, mementourile, segmentele de metri orbi în roșu și poziția la SOS.

### 5. Panoul regizorului și redarea
- **Comenzile din panou** (butoane și taste):
  - salt la scenele 1–10;
  - pornire / pauză;
  - timp ×1 / ×20;
  - slider de viteză;
  - oprire la următorul POI;
  - **oprirea LLM-ului**;
  - ocupanți declarați în spate;
  - resetare.
- **`simulator/replay.py`:**
  - la repetiții înregistrezi `PerceptionFrame`-urile fiecărei scene în `tests/scenes/<n>.jsonl`;
  - în modul redare le trimiți pe `/ws/perception`, în locul lui P1.

### 6. DriveMate Contact complet, profilurile, prezentarea
- **Pagina `/c/{token}`:**
  - starea șoferului: conduce sau e oprit, ETA;
  - câmpul de mesaj;
  - **notificarea galbenă „{nume} pare obosit”** (C10/F8), cu butonul „Scrie-i lui {nume}”;
  - **alerta roșie SOS**, cu harta live și raportul.
- **`profiles/<nume>/profile.json`:**
  - nume, rol, gusturi muzicale;
  - `safe_contact` și `emergency_contact`, **doar cu numele**. Numerele stau în `.env`;
  - `consent.safe_contact_notify` și `announce`.
- **Prezentarea** pe template (secțiunea 15), **README-ul** în engleză și **QR-ul**.

### Adăugat de P3: YouTube la cerere (D11, prioritate S, v2.2)
P3 a implementat căutarea și redarea de pe YouTube (ramura `p3-youtube-media`, `docs/assistant.md` §6.1). Vocea (`dashboard/src/voice/`) redă deja audio-ul, deci nu ai nimic obligatoriu de făcut. Ce ar fi util:
- **`.env.example`:** adaugă `YOUTUBE_API_KEY=` (opțional; fără cheie căutarea merge prin yt-dlp, doar mai lent, și fără SafeSearch când e copil la bord).
- **Proxy de dezvoltare (Vite):** `/media/yt/*` trebuie trimis la core, la fel ca `/tts/*` și `/media/*`.
- **Dashboard-ul de acum** e pentru partea de computer vision. **Interfața vizuală pentru utilizator** (pe care o plănuim) poate arăta:
  - „Acum se redă”: `state.media.title`, cu iconița sursei (`state.media.source`: `youtube` / `catalog`);
  - **variantele găsite, doar pentru pasager** (șoferul nu citește nimic): titlurile din `ask.options`. Core-ul trebuie să le publice; varianta propusă e un eveniment `media_choice` în jurnal sau un câmp în stare. Decizia e la P2 + P4;
  - un buton „oprește muzica” (`stop_media`).
- **Panoul regizorului (opțional):** un comutator YouTube pornit/oprit, dacă rețeaua din sală e slabă (`youtube.enabled` din `assistant.yaml`).
- **Slide-ul de confidențialitate:** linia nouă din §3 a planului („textul cererilor de muzică / podcast ajunge la YouTube”).

---

## Cum lucrezi fără ceilalți

- `scripts/fake_core.py` ține locul core-ului. UI-ul îl faci complet pe el.
- Pentru Contact și simulator ai nevoie doar de core (sau de un FastAPI minimal în `integrations/contact_app/dev.py`).
- Testele stau în `tests/dashboard/`: simulatorul (poziția la un `t` dat, oprirea la POI) și redarea scenelor.

## Calendar

| Când | Ce |
|---|---|
| 02:00 | scheletul + primul commit + cele 4 ramuri; Contact minimal prin tunel; `fake_core.py` |
| Sâmbătă 12:00 | dashboard live pe core (video, grafic, jurnal, alarmă vizibilă); simulatorul merge |
| Sâmbătă 22:00 | tot ce e M: performanța, fișa, harta, regizorul, redarea, Contact complet |
| Duminică | prezentarea, README-ul, QR-ul; conduci repetițiile (panoul regizorului) |

## Reguli comune (pe scurt; detaliile sunt în secțiunea 13 din plan)

- **Ramura ta:** `p4-dashboard`. Faci commit pe fiecare funcție, cu mesaj în engleză și prefixul modulului: `dashboard: add performance panel`.
- **Înainte de fiecare punct de control:** `git fetch origin && git merge origin/main`, testele, `git push`. La merge în `main` ești ultimul (P2 → P1 → P3 → P4).
- **Câmp nou în stare?** Anunți pe grup (`CONTRACT: …`). Câmpurile noi sunt opționale, cu valoare implicită.
- **Cheile, tokenul paginii Contact și numerele de telefon** stau doar în `.env`. **Claude nu face commit sau push.**

## Blocul pentru `CLAUDE.local.md`

```
Lucrez ca P4 (dashboard + simulator + DriveMate Contact + repo) în proiectul DriveMate.
Citește roluri/P4-dashboard-simulator-contact.md și secțiunile 4.H, 4.I, 4.J, 9, 12, 13, 15 din DriveMate-PLAN-FINAL.md.
Lucrez în principal în: dashboard/** (vocea din dashboard/src/voice/ o face P3), simulator/**,
integrations/contact_app/**, integrations/__init__.py, profiles/**, scripts/fake_core.py,
tests/dashboard/**, tests/scenes/**, presentation/**, docs/, README.md, run.sh, .env.example,
.gitignore, requirements.txt, requirements/p4-dashboard.txt.
Dacă trebuie modificat ceva în afara lor (de ex. shared/contracts.py), spune-mi înainte, ca să anunț echipa.
Nu scrie numere de telefon sau chei în fișierele din repo; doar în .env.
Nu face niciodată commit sau push.
```
