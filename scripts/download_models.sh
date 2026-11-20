#!/usr/bin/env bash
# Download, export and verify the P1 models into perception/models/ (gitignored).
#
#   bash scripts/download_models.sh          # skip files that are already present and valid
#   bash scripts/download_models.sh --force  # re-download and re-export everything
#
# Sources are fixed, verified URLs (checked 2026-11-20). If one fails, the script stops and prints it:
# do not replace it with a guessed URL.
# Needs: curl, and the project venv (Python with ultralytics, onnx, onnxruntime[-gpu]; openvino optional).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/perception/models"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then PY="$ROOT/.venv/Scripts/python.exe"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
else PY="python3"; fi

mkdir -p "$DEST"

# file | url | minimum size in bytes
MODELS=(
    "face_landmarker.task|https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task|3000000"
    "gesture_recognizer.task|https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task|7000000"
    "face_detection_yunet_2023mar.onnx|https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx|200000"
    "face_recognition_sface_2021dec.onnx|https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx|35000000"
    "mobileone_s0_gaze.onnx|https://github.com/yakhyo/gaze-estimation/releases/download/weights/mobileone_s0_gaze.onnx|4000000"
    "yolo26n.pt|https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt|5000000"
    "yolo26s.pt|https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt|19000000"
)

size_of() { wc -c <"$1" | tr -d ' '; }

echo "== downloading into $DEST"
for entry in "${MODELS[@]}"; do
    IFS='|' read -r file url min <<<"$entry"
    target="$DEST/$file"
    if [[ $FORCE -eq 0 && -f "$target" && "$(size_of "$target")" -ge "$min" ]]; then
        echo "ok    $file (already present, $(size_of "$target") B)"
        continue
    fi
    echo "get   $file"
    if ! curl --fail --location --retry 2 --silent --show-error -o "$target.part" "$url"; then
        rm -f "$target.part"
        echo "ERROR: download failed for $file" >&2
        echo "       URL: $url" >&2
        echo "       Stopping. Check the URL by hand; do not substitute a guessed one." >&2
        exit 1
    fi
    got="$(size_of "$target.part")"
    if [[ "$got" -lt "$min" ]]; then
        rm -f "$target.part"
        echo "ERROR: $file is $got B, expected >= $min B (URL: $url)" >&2
        exit 1
    fi
    mv "$target.part" "$target"
    echo "ok    $file ($got B)"
done

echo "== exporting YOLO26 to ONNX (+ OpenVINO if installed)"
YOLO_AUTOINSTALL=false "$PY" - "$DEST" "$FORCE" <<'PY'
import importlib.util
import shutil
import sys
from pathlib import Path

from ultralytics import YOLO

dest, force = Path(sys.argv[1]), sys.argv[2] == "1"
has_openvino = importlib.util.find_spec("openvino") is not None
variants = {"yolo26n": [320, 416, 640], "yolo26s": [640]}

for stem, sizes in variants.items():
    weights = dest / f"{stem}.pt"
    for size in sizes:
        onnx_out = dest / f"{stem}_{size}.onnx"
        # nms=False keeps YOLO26's end-to-end NMS-free head: output [1, 300, 6] = x1, y1, x2, y2, score, class.
        # (With the default nms=None, Ultralytics exports the raw [1, 84, N] head that needs NMS.)
        if force or not onnx_out.exists():
            exported = Path(YOLO(str(weights)).export(format="onnx", imgsz=size, dynamic=False, simplify=True,
                                                      nms=False, device="cpu", verbose=False))
            shutil.move(str(exported), onnx_out)
            print(f"ok    {onnx_out.name}")
        else:
            print(f"ok    {onnx_out.name} (already present)")
        if has_openvino:
            ov_out = dest / f"{stem}_{size}_openvino_model"
            if force or not ov_out.exists():
                exported_dir = Path(YOLO(str(weights)).export(format="openvino", imgsz=size, nms=False,
                                                              device="cpu", verbose=False))
                if ov_out.exists():
                    shutil.rmtree(ov_out)
                shutil.move(str(exported_dir), ov_out)
                print(f"ok    {ov_out.name}/")
            else:
                print(f"ok    {ov_out.name}/ (already present)")
if not has_openvino:
    print("skip  OpenVINO export (openvino not installed)")
PY

echo "== verifying"
"$PY" - "$DEST" <<'PY'
import hashlib
import sys
import zipfile
from pathlib import Path

import onnxruntime as ort

ort.set_default_logger_severity(3)  # SFace triggers harmless "initializer in graph inputs" warnings
dest = Path(sys.argv[1])
errors: list[str] = []
sums: list[str] = []

for path in sorted(dest.iterdir()):
    if not path.is_file() or path.name == "SHA256SUMS":
        continue
    if path.suffix == ".task":
        if not zipfile.is_zipfile(path):  # MediaPipe bundles are zips (with 2 leading bytes before "PK")
            errors.append(f"{path.name}: not a MediaPipe .task bundle (zip)")
            continue
        print(f"ok    {path.name}: MediaPipe bundle")
    elif path.suffix == ".onnx":
        try:
            sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        except Exception as exc:
            errors.append(f"{path.name}: onnxruntime cannot load it ({exc})")
            continue
        ins = ", ".join(f"{i.name}{list(i.shape)}" for i in sess.get_inputs())
        outs = ", ".join(f"{o.name}{list(o.shape)}" for o in sess.get_outputs())
        if path.name.startswith("yolo26") and list(sess.get_outputs()[0].shape)[-1] != 6:
            errors.append(f"{path.name}: expected the end-to-end head [1, 300, 6], got {outs} (re-run with --force)")
            continue
        print(f"ok    {path.name}: in {ins} -> out {outs}")
    sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")

(dest / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
print(f"wrote {dest / 'SHA256SUMS'} ({len(sums)} files)")
if errors:
    print("\n".join("ERROR: " + e for e in errors), file=sys.stderr)
    sys.exit(1)
PY
echo "== all models present and verified"
