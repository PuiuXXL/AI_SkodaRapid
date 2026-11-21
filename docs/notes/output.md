# Ieșirea percepției (worker, main, stream, perf, frame_builder): note de integrare

Sesiunea IEȘIRE (worktree `p1-output`). Arhitectura cu procese rămâne cea din `docs/perception.md` §2; aici e ce s-a
schimbat și ce trebuie făcut la integrare.

## Ce face fiecare fișier

| Fișier | Rol |
|---|---|
| `perception/worker.py` | `CameraWorker` (procesul spawn al camerei, cozi maxsize 1, repornire cu backoff, camera `available=false` cât e oprită) + **interfața injectată** `CameraPipeline` / `PipelineModule` + `ModularPipeline` (implicit) cu modulele built-in `detectors`, `calibration` (doar șofer), `phone`, `gesture`, `monitoring` |
| `perception/frame_builder.py` | rezultatele cele mai noi → `PerceptionFrame` validat; `ts` la captură; vârsta datelor; `frame_patch` + `register_mapper` pentru module noi |
| `perception/main.py` | asyncio: workerii, publicare la `publish_hz`, WS cu backoff (outage logat o dată), rutarea comenzilor după capabilitățile workerului, CLI |
| `perception/stream.py` | MJPEG aiohttp pe `:8001` (`/video/driver`, `/video/passenger`, `/`, `/health`); workerul codează JPEG doar cât timp există clienți |
| `perception/perf.py` | ferestre p50/p95 (`deque(maxlen=120)`), fps, CPU/RAM/GPU + `build_perf_block` (blocul `perf.*` din contract) |
| `perception/config/pending/output.yaml` | chei noi de config, până intră în `perception.yaml` |

Regula de degradare rămâne în `perception/degrade.py` (neschimbat): p95 e2e > `rates.degrade_e2e_p95_ms` → întâi
rata pasagerului, apoi YOLO; fața șoferului niciodată. **Corectat în main:** pasagerul primea două comenzi `rates` pe
pas, iar copia persistată (retrimisă după o repornire) o păstra doar pe ultima, deci după o repornire se pierdea rata
feței pasagerului. Acum fiecare cameră primește o singură comandă `rates` cu ambele valori.

## De integrat

### 1. Cum se adaugă un modul nou (hands, phone, identity, monitoring, head_answer)

Un modul rulează în procesul camerei, după cele built-in, pe fiecare cadru procesat:

```python
# perception/driver_cam/head_answer.py (exemplu)
from typing import Any
from perception.features import FeatureFrame
from perception.worker import CameraContext, FrameInput

class HeadAnswerModule:
    name = "head_answer"
    commands = frozenset({"dialog_window"})     # comenzile pe care le vrea; main le rutează automat

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        self.ctx = ctx                          # ctx.cfg, ctx.name ("driver"/"passenger"), ctx.width/height/fps
        self.open_until: float | None = None

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") == "dialog_window":   # o comandă ajunge la TOATE modulele (și la gesture)
            self.open_until = cmd.get("until_perf") if cmd.get("open") else None
            return True
        return False

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any] | None:
        state = inp.shared["state"]             # DriverState de la modulul detectors (și: ff, luma, monitoring)
        answer = ...                            # "yes" / "no" / None
        block = "driver" if self.ctx.name == "driver" else "passenger"
        patch = {"head": {"answer": answer}} if block == "driver" else {"answer": answer}
        return {
            "head_answer": {"answer": answer},  # în mesajul workerului (debug, /health), cheie = numele modulului
            "frame_patch": {block: patch},      # frame_builder îl face deep-merge în PerceptionFrame
        }

    def close(self) -> None: ...
    # opțional: def draw(self, img, inp) -> None   (desenează în overlay-ul de debug)
```

Înregistrarea, **fără să modifici worker.py**:
- în `perception/config/pending/output.yaml` (după integrare: `perception.yaml`):
  ```yaml
  workers:
    modules:
      driver: ["perception.driver_cam.head_answer:HeadAnswerModule"]
      passenger: ["perception.driver_cam.head_answer:HeadAnswerModule"]
  ```
- sau un pipeline complet altul: `Perception(..., factory="pkg.mod:make_pipeline")` /
  `CameraWorker(..., factory=...)`; factory-ul primește `(ctx, perf)` și întoarce un obiect `CameraPipeline`
  (`commands`, `process`, `handle`, `render`, `close`). `tests/perception/test_worker.py::EchoPipeline` e un exemplu
  care împachetează pipeline-ul implicit.

Reguli:
- **Ieșirea în PerceptionFrame:** `frame_patch` (dict în forma frame-ului). Pentru liste (de ex.
  `occupants[].profile` de la identity) se înregistrează un mapper în frame_builder:
  ```python
  @register_mapper("identity")
  def _identity(frame, msg, camera, cfg):
      seat = "driver" if camera == "driver" else "front_right"
      for occ in frame["occupants"]:
          if occ["seat"] == seat:
              occ["profile"] = msg["identity"]["profile"]
  ```
- **Un patch invalid** (încalcă contractul) nu oprește fluxul: frame-ul pleacă fără patch-uri, eroarea e logată o dată.
- **Un modul extra care aruncă excepție** e logat o dată și sărit pe cadrul respectiv; camera merge mai departe.
  Erorile modulelor built-in opresc procesul (repornire automată), ca înainte.
- **Perf:** un model nou se cronometrează cu `perf.time("<nume>")` (tracker-ul procesului e în factory) sau cu o
  `LatencyWindow` proprie. Numele `sface` și `pose` umplu automat `perf.sface_ms_p50` / `perf.pose_ms_p50`
  (`perception/perf.py`, `MODEL_FIELDS`). Fiecare modul mai are o etapă `<nume>_module` în `perf.stages_ms`.
- **Înlocuirea unui built-in** (de ex. modulul phone nou în locul lui `PhoneModule`, sau monitoring nou): o linie
  în `default_pipeline()` din worker.py, sau un factory propriu. Câmpurile din mesaj pe care le citește
  frame_builder pentru phone/monitoring sunt `phone{in_use, conf, near_face, side}` și
  `monitoring{ok, reason, face_missing_s}`; un modul nou cu altă formă trebuie să scrie aceleași chei sau să treacă
  pe `frame_patch`.

### 2. Comenzile suportate

Formatul de la core: `{"cmd": ...}` sau `{"type": "<cmd>", ...}`; fiecare primește
`{"type": "ack", "cmd", "status", "detail"}`.

| Comandă | Unde ajunge | Ack |
|---|---|---|
| `debug {on}` | toate camerele (persistent, retrimis după repornire) | `ok` |
| `dialog_window {open, to, until}` | camera țintă (`to`: `"passenger"` / `2` → pasager, altfel șofer); `until` = `time.time()` de închidere, implicit 6 s | `ok` / `error` dacă acea cameră nu rulează |
| `calibrate {profile, quick}` | șofer (modulul calibration) | `started`, apoi `calibration_prompt` pe fiecare pas, apoi `done` / `error` |
| `enroll {name}` și orice comandă nouă | camera țintă, **doar dacă un modul o declară în `commands`** | `ok`; `not_implemented` + log dacă niciun modul nu o tratează; `queued` dacă workerul încă n-a raportat capabilitățile |
| `rates {face_hz, phone_hz}` | intern (regula de degradare) | — |

Capabilitățile fiecărei camere apar în `/health` (`cameras.<cam>.commands`) și în fiecare mesaj de worker
(`commands`). Când modulul identity declară `enroll`, rutarea merge fără nicio schimbare în main.

### 3. Chei de config de mutat

Din `perception/config/pending/output.yaml` în `perception/config/perception.yaml` + `perception/config.py`:
- `output.result_max_age_ms` (`OutputConfig`, `PositiveFloat`): rezultat de cameră mai vechi = fără date;
- `output.mjpeg_host` (`OutputConfig`, `str`);
- `workers.modules` (`WorkersConfig`, `dict[Literal["driver","passenger"], list[str]]`).

Apoi în `perception/main.py`: `PendingConfig` / `load_pending` se șterg, iar `Perception` citește `cfg.output.*` și
`cfg.workers.modules`. Flag-ul `--pending-config` dispare.

### 4. Texte de actualizat în fișiere care nu sunt ale acestei sesiuni

- `docs/perception.md` §2.2: `ts` = captura celui mai nou cadru de șofer (nu publicarea); `--source synthetic`
  (`--synthetic` rămâne alias), `--device N`; MJPEG în `perception/stream.py`, frame-ul în
  `perception/frame_builder.py`; module injectabile (secțiunea 1 de mai sus); vârsta datelor
  (`result_max_age_ms`).
- `perception/contract.py`: comentariul de la `PerceptionFrame.ts` spune „time.time() of publication” → „of capture
  of the newest driver frame”.

### 5. CLI

```powershell
python -m perception.main --print --no-ws                  # frame-uri JSON pe stdout, fără core
python -m perception.main --print --no-ws --device 0       # camera laptopului pentru rularea asta (yaml neschimbat)
python -m perception.main --source synthetic --no-models   # fără cameră și fără modele (CI)
python -m perception.main                                  # spre ws://localhost:8000/ws/perception + MJPEG :8001
python scripts/ws_sink.py --send debug --send dialog_window   # în locul core-ului, până există
```

## Texte CONTRACT

`PerceptionFrame` (provizoriu și planul §7) are deja `ts` și `seq`; lipsesc semantica lui `ts` și vârsta per cameră.
`shared/contracts.py` nu există încă: validarea folosește `perception/contract.py`, care trece automat pe modelul lui
P2 când apare.

```
CONTRACT: ts, float, P1, = time.time() la CAPTURA celui mai nou cadru al șoferului (nu la publicare); fallback = ora publicării când camera șoferului nu are date proaspete; P2 compară cu evenimentele din core și din browser
CONTRACT: perf.publish_ts, float|null (default null), P1, time.time() la publicarea frame-ului; publish_ts - ts = vârsta datelor la plecare
CONTRACT: perf.cameras.<cam>.capture_ts, float|null (default null), P1, time.time() la captura ultimului cadru folosit din camera respectivă
CONTRACT: perf.cameras.<cam>.age_ms, float|null (default null), P1, vârsta rezultatului camerei la publicare; peste prag (result_max_age_ms) datele camerei nu se folosesc și available=false
CONTRACT: perf.cameras.<cam>.dropped_results, int (default 0), P1, rezultate înlocuite în coada worker→main înainte să fie citite (J1)
```

Celelalte câmpuri propuse (`perf.cameras.<cam>.available`, `perf.degrade_level`, `perf.stages_ms`,
`driver.monitoring_*`, ...) au textele lor în `docs/perception.md` §9.

## Măsurat (2026-11-21, laptopul de dezvoltare, camera integrată `--device 0`, celelalte 2 sesiuni rulând în paralel)

- `--print --no-ws`, 30 s: **15,01 Hz** publicat, 451/451 frame-uri valide, `seq` continuu, fața văzută în 100 %
  din cadrele cu cameră; vârsta datelor p50 66 ms (max 208); `face_driver_ms_p50` 10 ms; captură 29,7 fps,
  procesare 22 fps; `e2e_ms_p95` 142 ms (aproape de pragul de 150 ms, cu CPU-ul împărțit cu celelalte sesiuni;
  docs/perception.md §2.2 avea 55–82 ms singur); CPU 44 %, RAM 1,1 GB.
- Pornire: ~15 s până la primul frame cu date (camera ~4 s, modelele ~11 s cu CPU-ul ocupat); până atunci frame-urile
  pleacă valide, cu `available=false`.
- MJPEG: `/video/driver` 640 px, ~8 cadre/s măsurate pe 3 s cu curl (inclusiv pornirea codării); clienții revin la 0
  după deconectare; `/video/passenger` → 404 când pasagerul nu e activat.
- WS (`scripts/ws_sink.py` în locul core-ului): 448 frame-uri, 0 invalide, 15,0 Hz; ack `debug` și `dialog_window` = `ok`.
