# P1: computer vision (percepție)

> Citește întâi `DriveMate-PLAN-FINAL.md`: secțiunile 4.A, 7, 8, 9 și 13. Fișierul ăsta îți spune ce faci, în ce ordine, cum și ce ai voie să atingi.

## Misiunea ta

Transformi cele două camere într-un flux `PerceptionFrame`, de 15 ori pe secundă: rapid, stabil și fără alarme false.
Tot demo-ul se bazează pe tine:
- dacă EAR-ul tremură, alarma sună degeaba;
- dacă zonele de privire greșesc, privirea în oglindă dă alertă;
- dacă telefonul nu e detectat, scena 3 nu are sens.

**Tu raportezi ce vezi. Ce înseamnă (oboseală, risc, alarmă) decide P2.**

---

## Unde lucrezi

- `perception/**`, inclusiv `perception/config/perception.yaml`
- `scripts/benchmark.py`, `scripts/enroll_face.py`, `scripts/calibrate.py`, `scripts/download_models.sh`
- `tests/perception/**`, `docs/perception.md`, `requirements/p1-perception.txt`

La rulare, codul tău **scrie** `profiles/<nume>/calibration.json` și `profiles/<nume>/face.npy`. Ambele sunt în `.gitignore` și **nu intră în git**.

Dacă ai nevoie de o schimbare în altă parte (de exemplu un câmp nou în `shared/contracts.py`), anunță pe grup, ca să nu lucrați doi oameni în același fișier în același timp.

---

## Interfețele tale

| Direcție | Ce | Unde |
|---|---|---|
| **Ieși** | `PerceptionFrame`, 15 Hz | client WebSocket spre `ws://localhost:8000/ws/perception` |
| **Intră** | comenzi de la core: `dialog_window` (deschisă / cui / până când), `calibrate` (profil), `debug` (on/off), `enroll` (nume) | același WebSocket |
| **Ieși** | video cu overlay | MJPEG pe `http://localhost:8001/video/driver` și `/video/passenger`, 640 px, JPEG 70, 10–15 fps |

**Câmpurile pe care le scrii tu:**
- `driver.eyes`, `driver.head`, `driver.gaze`, `driver.yawn`, `driver.speaking`, `driver.phone`, `driver.gesture`;
- identitatea din `occupants` (pentru șofer și dreapta);
- tot blocul `passenger`;
- `perf.cameras` și `perf.*_ms_*`.

**Nu calculezi:** reacția, F, D, atenția, riscul, cauza, conversația, alarmele. Toate sunt la P2.

**Pragurile de percepție** stau în `perception/config/perception.yaml`: EAR, histerezis, durate minime, încrederi, pragul SFace. Pragurile de siguranță (când sună alarma) sunt ale lui P2.

---

## Pașii, în ordine

### 1. În seara asta, până la 02:00: captură și benchmark
- **`perception/capture.py`**: clasa `LatestFrameCamera(src)`. Un thread citește continuu `cv2.VideoCapture(src)`, cu `CAP_PROP_BUFFERSIZE=1`, și păstrează **doar ultimul cadru**, plus `time.perf_counter()`. Faci câte una pentru webcam (șofer) și pentru DroidCam (pasager).
- **DroidCam pe USB:**
  - pe telefon: aplicația DroidCam, cu depanarea USB activată (`adb`);
  - pe laptop: clientul DroidCam. Pe Linux, el creează un dispozitiv `/dev/videoN` prin `v4l2loopback`.
- **`scripts/download_models.sh`:**
  - Face Landmarker și Gesture Recognizer (`.task`);
  - YOLO26n și YOLO26n-pose;
  - YuNet și SFace (ONNX din OpenCV Zoo).
- **`scripts/benchmark.py`**: rulează fiecare model pe ~300 de cadre, pe **laptopul de demo**, și scoate un tabel p50/p95 în Markdown.
- ✅ **Gata când:** ambele camere merg simultan, iar tabelul de benchmark e pe grup.

### 2. Camera șoferului: fața
- **Face Landmarker** în modul VIDEO, cu `output_face_blendshapes=True` și `output_facial_transformation_matrixes=True`.
  - Rulează pe **decupajul feței**: zona din reperele cadrului anterior, mărită ~1,6×.
  - Dacă fața se pierde, rulezi o dată pe tot cadrul.
- **EAR pe fiecare ochi.** Indicii folosiți de obicei cu MediaPipe sunt:
  - ochiul drept: `33, 160, 158, 133, 153, 144`;
  - ochiul stâng: `362, 385, 387, 263, 373, 380`.

  Folosești ochiul văzut mai bine și îl raportezi în `eye_used`.
- **Ochi închis / deschis** cu histerezis (de exemplu sub 0,18 închis, peste 0,23 deschis) și o durată minimă de ~300 ms. De aici scoți:
  - `blink_ms`;
  - `closed_ms`;
  - PERCLOS pe 60 s, dintr-un `deque` cu timestamp-uri.
- **Căscat:** blendshape-ul `jawOpen` peste prag cel puțin 2 s.
- **Capul:** yaw, pitch și roll din matricea de transformare.
- **Căderea capului de oboseală (`nodding`):** pitch-ul scade cu peste 15° în mai puțin de 1,5 s, cu ochii care se închid.
- **Vorbește:** varianța lui `jawOpen` pe o fereastră de 1 s trece de prag.
- **Filtrele** stau în `perception/filters.py`: EMA, histerezis, durată minimă. Când încrederea e mică, raportezi `unknown`.
- ✅ **Gata când:** clipitul, ochii închiși, căscatul și capul apar corect live în overlay, fără să tremure.

### 3. Zonele de privire
- **Trăsăturile:** yaw, pitch și poziția irisului față de colțurile ochiului (reperele irisului sunt 468–477).
- **Calibrarea** (`scripts/calibrate.py` sau comanda `calibrate` de la core):
  - ~2 s pe fiecare zonă: drum, oglinda stângă, oglinda dreaptă, retrovizor, bord, ecran, poală, **pasager**;
  - pe baza lor antrenezi un kNN (k = 5);
  - salvezi rezultatul în `profiles/<nume>/calibration.json`;
  - o distanță prea mare față de toate zonele înseamnă `unknown`.
- **Măsurătorile din zone:**
  - `off_road_ms`;
  - VATS: privirile în afara drumului mai scurte de 2 s, numărate pe 60 s;
  - entropia distribuției pe zone, pe 60 s.
- ✅ **Gata când:** pe montajul real, privirea în oglindă e recunoscută ca `mirror_left` de 10 ori din 10, iar privirea spre pasager ca `passenger`.

### 4. Telefonul, răspunsul din cap, gesturile, identitatea (șofer)
- **Telefonul:**
  - YOLO26n (clasa 67, încredere peste 0,4), rulat la 5 Hz pe zona mâinilor (din încheieturile YOLO26n-pose);
  - plus încheietura lângă față → `phone.source = "detector"`;
  - **tiparul „poală”**: cel puțin 3 priviri spre `lap` în 20 s, sau una mai lungă de 2 s, cu mâinile nevăzute → `"lap_pattern"`, cu încredere mai mică.
- **Răspunsul din cap.** Îl cauți **doar când core-ul a deschis fereastra de dialog**:
  - cel puțin 2 schimbări de sens ale pitch-ului (da) sau ale yaw-ului (nu) în mai puțin de 1,2 s;
  - amplitudinea peste prag;
  - ochii deschiși.

  Rezultatul merge în `head.answer`.
- **Gesturile:** MediaPipe Gesture Recognizer (`Thumb_Up`, `Thumb_Down`, `Open_Palm`), rulat doar în fereastra de dialog sau când mâna e ridicată.
- **Identitatea:**
  - `cv2.FaceDetectorYN` (YuNet) și `cv2.FaceRecognizerSF` (SFace), cu similaritate cosinus ≥ ~0,36 (pragul recomandat de OpenCV; îl ajustezi în yaml);
  - înrolarea: `scripts/enroll_face.py --name andrei` ia 10 cadre și salvează `profiles/andrei/face.npy`.

### 5. Camera pasagerului
- Aceeași față, la 10 Hz. De aici scoți:
  - `present`;
  - `awake` (ochi închiși mai mult de 10 s și capul lăsat înseamnă adormit);
  - `speaking`;
  - `holding_phone` (YOLO și încheieturile);
  - identitatea;
  - `answer`, când fereastra de dialog e adresată pasagerului.

### 6. Monitorizarea, debug-ul, performanța
- **`monitoring_ok=false`** când:
  - fața șoferului lipsește mai mult de 2 s fără o explicație;
  - sau cadrul nu se mai schimbă (camera e înghețată).

  Pentru pasager faci la fel, cu `passenger.present=false`.
- **Overlay-ul de debug** (comanda `debug`, tasta D din dashboard): repere, raza privirii, zona, EAR live, încheieturi, telefon, fps.
- **`perf`:** măsori cu `time.perf_counter()` în jurul fiecărui model și ții un `deque(maxlen=120)` pentru p50/p95.
- **Regula de degradare:** dacă latența p95 trece de 150 ms, scazi întâi frecvența camerei pasagerului, apoi pe cea a YOLO. **Fața șoferului nu se degradează niciodată.**

### 7. Duminică
- Reglezi `perception.yaml` în sală, pe lumina reală, și recalibrezi zonele pe montajul final.

---

## Cum lucrezi fără ceilalți

- `python -m perception.main --print --no-ws` afișează `PerceptionFrame`-urile în terminal. Nu ai nevoie de core.
- Când core-ul există, `./run.sh` pornește tot.
- Testele stau în `tests/perception/`. Folosești serii sintetice trecute prin filtre, de exemplu o serie de EAR cu un clipit de 200 ms și un microsomn de 1,5 s. **Nu înregistrăm video**, nici pentru teste.

## Calendar

| Când | Ce trebuie să meargă |
|---|---|
| 02:00 | ambele camere + benchmark-ul |
| Sâmbătă 12:00 | ochi, cap, zone de privire, telefon → în core, live |
| Sâmbătă 22:00 | tot ce e M în tabelele AS și AP |
| Duminică | reglaje în sală |

## Reguli comune (pe scurt; detaliile sunt în secțiunea 13 din plan)

- **Ramura ta:** `p1-perception`. Faci commit pe fiecare funcție, cu mesaj în engleză și prefixul modulului: `perception: add PERCLOS window`.
- **Înainte de fiecare punct de control:** `git fetch origin && git merge origin/main`, rulezi testele tale, apoi `git push`.
- **La punctul de control:** merge în `main` pe rând, în ordinea P2 → P1 → P3 → P4.
- **Câmp nou în contract?** Anunți pe grup (`CONTRACT: …`). Câmpurile noi sunt opționale, cu valoare implicită.
- **Cheile** stau doar în `.env`. **Claude nu face commit sau push.**

## Blocul pentru `CLAUDE.local.md`

```
Lucrez ca P1 (computer vision) în proiectul DriveMate.
Citește roluri/P1-computer-vision.md și secțiunile 4.A, 7, 8, 13 din DriveMate-PLAN-FINAL.md.
Lucrez în principal în: perception/**, scripts/benchmark.py, scripts/enroll_face.py,
scripts/calibrate.py, scripts/download_models.sh, tests/perception/**, docs/perception.md,
requirements/p1-perception.txt.
Dacă trebuie modificat ceva în afara lor (de ex. shared/contracts.py), spune-mi înainte, ca să anunț echipa.
Pragurile stau în perception/config/perception.yaml, niciodată în cod.
Nu înregistra video. Nu face niciodată commit sau push.
```
