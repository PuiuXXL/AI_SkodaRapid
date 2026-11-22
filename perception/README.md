# P1 · Perception

[Project setup](../README.md) · [Technical decisions](../docs/perception.md) · [Original role brief](../roluri/P1-computer-vision.md)

P1 converts driver/passenger camera images into contract-validated observations. Its output is a `PerceptionFrame` at a configured 15 Hz, plus MJPEG camera previews. Core interprets those observations and decides risk and interventions.

## Tech stack

| Technology | Use |
| --- | --- |
| Python 3.11; CI also on 3.12 | Runtime, typed configuration and orchestration |
| OpenCV | Capture, image preprocessing, YuNet/SFace, JPEG overlays |
| MediaPipe Tasks | Face landmarks and gesture recognition |
| ONNX Runtime | Gaze, face/identity and exported detector inference |
| Ultralytics / YOLO26 | Phone detection and model export; rear-seat pose where configured |
| NumPy | Features, geometry and embeddings |
| multiprocessing + bounded queues | Isolated camera workers, latest results and supervision |
| websockets | Bidirectional transport to core |
| aiohttp | MJPEG server |
| Pydantic, PyYAML, orjson | Configuration, shared validation and serialization |
| psutil | Resource/latency diagnostics |
| pytest, Ruff, Mypy | Regression tests, lint and static types |

Model licences differ. MediaPipe/Open Model Zoo models and YOLO have their own distribution terms. Review the model sources and the Ultralytics AGPL licence when redistributing or deploying.

## Implementation

1. `capture.py` reads the newest camera frame and tracks capture time, availability and device assignment.
2. `worker.py` runs each camera in its own process, with bounded command/result queues, heartbeats and restart backoff.
3. `extractor.py`, `modules.py` and `driver_cam/` turn images into features and observations.
4. Driver modules measure eyes, gaze, head pose, nods, mouth activity and rear glances. Additional modules handle identity, hands/gestures, phone use and posture.
5. `monitoring.py` marks low-quality or absent observations; missing frames are not treated as a safe driver state.
6. `frame_builder.py` assembles the shared contract. `main.py` publishes it and routes commands/acknowledgements.
7. `stream.py` serves JPEG previews. `degrade.py` adjusts processing load while exposing the degradation level.

The system separates wall-clock timestamps used on the wire from monotonic timing used for processing and duration measurements.

## Interfaces

| Interface | Data |
| --- | --- |
| `ws://localhost:8000/ws/perception` | Frames out, commands in, acknowledgements/events out |
| `http://localhost:8001/video/driver` | Driver MJPEG |
| `http://localhost:8001/video/passenger` | Passenger MJPEG |
| `shared/contracts.py` | Shared field types and command vocabulary |

Commands include `debug`, `dialog_window`, `enroll` and `calibrate`. Gaze calibration targets the driver. Persistent worker state ensures one-off enrolment/calibration results are not lost when newer frames replace older ones.

## Install and start

From the repository root, with the virtual environment active:

```bash
python -m pip install -r requirements/p1-perception.txt -r requirements/p1-dev.txt
bash scripts/download_models.sh
python -m core.main
```

In another terminal:

```bash
python -m perception.main
```

The downloader selects the project environment when present. It downloads, validates and exports the files under `perception/models/`. On Linux install the OpenCV/MediaPipe system libraries listed in the root README.

### Single webcam

```bash
python -m perception.main --device 0 --passenger off
```

The checked-in USB IDs target the team's two webcams. Override them in `perception/config/perception.yaml` or use `--device`. Device identification and camera troubleshooting are detailed in `docs/perception.md`.

### Synthetic worker smoke test

```bash
python -m perception.main --source synthetic --no-models --seconds 10
python -m perception.main --source synthetic --no-models --no-ws --no-mjpeg --print --seconds 3
```

This tests capture/worker/transport behaviour without model files or cameras. Synthetic images contain no meaningful face observations. The separate `scripts.fake_perception` source is intended for semantic fatigue/distraction demos.

### Configuration and acceleration

- `--config PATH` selects another validated YAML configuration.
- `--passenger auto|on|off` controls the second worker.
- `--no-mjpeg`, `--mjpeg-port`, `--no-ws` and `--log-level` control outputs.
- The YAML contains model paths, filters, gaze calibration, eye reliability and degradation thresholds.
- CPU uses `onnxruntime`. An NVIDIA setup can replace it with `onnxruntime-gpu` and compatible CUDA/cuDNN. Install only one ONNX Runtime provider package.
- The requirements file documents GPU PyTorch installation for YOLO on Windows.
- Eye CNN support is configurable and currently disabled in the checked-in configuration. Its presence among downloaded models does not imply that it is enabled.

Biometric embeddings and calibration files belong under `profiles/<name>/` and are ignored by Git. Feature recordings and diagnostics belong under ignored `data/`.

## Verification

```bash
python -m ruff check
python -m mypy
python -m pytest tests/perception tests/contract -m "not models and not camera" -q
python -m pytest tests/integration -m slow -q
```

Contract tests also instantiate core, so install `requirements/p2-core.txt` when running the combined suite. Full model tests require downloaded models:

```bash
python -m pytest tests/perception -m "models and not camera" -q
```

The perception workflow enforces 83% coverage. Hardware/model behaviour still needs the corresponding real-data checks documented under `docs/eval/`.
