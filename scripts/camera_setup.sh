#!/usr/bin/env bash
# Apply the fixed camera controls from perception/config/perception.yaml (cameras.<name>.controls) with v4l2-ctl.
#
#   scripts/camera_setup.sh driver            # apply controls to the driver camera
#   scripts/camera_setup.sh passenger --list  # show formats and controls the camera supports
#
# Linux only (v4l2-ctl, package v4l-utils). On Windows the same controls are applied best-effort by
# perception/capture.py through OpenCV properties. Controls the camera does not support are skipped with a message.
# Why these controls: docs/perception.md (camera controls).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    echo "usage: $0 <camera-name> [--list]   (camera-name: driver | passenger)" >&2
    exit 2
}

[[ $# -ge 1 ]] || usage
CAMERA="$1"
LIST=0
[[ "${2:-}" == "--list" ]] && LIST=1

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "camera_setup.sh: v4l2-ctl is Linux-only. On $(uname -s) the controls in perception.yaml are applied" \
         "by perception/capture.py (OpenCV properties, best effort; see its 'camera controls' log line)."
    exit 0
fi
command -v v4l2-ctl >/dev/null || { echo "v4l2-ctl not found: sudo dnf install v4l-utils (or apt install v4l-utils)" >&2; exit 1; }

if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
else PY="python3"; fi

# Validated config -> "key value" lines (empty value = null = leave untouched).
CONFIG_LINES="$(cd "$ROOT" && "$PY" - "$CAMERA" <<'PY'
import sys
from perception.config import load_config

name = sys.argv[1]
cams = load_config().cameras
if name not in type(cams).model_fields:
    sys.exit(f"unknown camera {name!r}; expected one of {list(type(cams).model_fields)}")
cam = getattr(cams, name)
print("device", cam.device)
for key, value in cam.controls.model_dump().items():
    if isinstance(value, bool):
        value = int(value)
    print(key, "" if value is None else value)
PY
)"

cfg() { awk -v k="$1" '$1 == k { $1 = ""; sub(/^ /, ""); print; exit }' <<<"$CONFIG_LINES"; }

DEVICE="$(cfg device)"
if [[ "$DEVICE" =~ ^[0-9]+$ ]]; then DEVICE="/dev/video$DEVICE"; fi
[[ -e "$DEVICE" ]] || { echo "device $DEVICE not found (cameras.$CAMERA.device)" >&2; exit 1; }

if [[ $LIST -eq 1 ]]; then
    echo "== $CAMERA: $DEVICE formats =="
    v4l2-ctl -d "$DEVICE" --list-formats-ext
    echo "== $CAMERA: $DEVICE controls =="
    v4l2-ctl -d "$DEVICE" --list-ctrls-menus
    exit 0
fi

SUPPORTED="$(v4l2-ctl -d "$DEVICE" --list-ctrls-menus | awk '/0x[0-9a-f]+/ { print $1 }')"

# First control name (of the candidates) that this camera/driver supports.
pick() {
    local name
    for name in "$@"; do
        if grep -qx "$name" <<<"$SUPPORTED"; then echo "$name"; return 0; fi
    done
    return 1
}

APPLIED=0
SKIPPED=0
set_ctrl() {  # set_ctrl <label> <value> <candidate names...>
    local label="$1" value="$2"; shift 2
    local name
    if ! name="$(pick "$@")"; then
        echo "skip  $label: not supported by this camera (tried: $*)"
        SKIPPED=$((SKIPPED + 1)); return 0
    fi
    if v4l2-ctl -d "$DEVICE" --set-ctrl="$name=$value" 2>/tmp/camera_setup.err; then
        echo "set   $label: $name=$value"
        APPLIED=$((APPLIED + 1))
    else
        echo "skip  $label: $name=$value rejected ($(tr -d '\n' </tmp/camera_setup.err))"
        SKIPPED=$((SKIPPED + 1))
    fi
}

echo "== $CAMERA: applying controls to $DEVICE =="

# Auto modes OFF first, then the manual values (drivers ignore manual values while auto is on).
POWER="$(cfg power_line_hz)"
if [[ -n "$POWER" ]]; then
    case "$POWER" in 0) menu=0 ;; 50) menu=1 ;; 60) menu=2 ;; *) menu="" ;; esac
    [[ -n "$menu" ]] && set_ctrl "power_line_hz=$POWER" "$menu" power_line_frequency
fi

AF="$(cfg autofocus)"
[[ -n "$AF" ]] && set_ctrl "autofocus" "$AF" focus_automatic_continuous focus_auto

AE="$(cfg auto_exposure)"
if [[ -n "$AE" ]]; then
    # V4L2 menu: 1 = manual, 3 = aperture priority (auto)
    if [[ "$AE" == "1" ]]; then ae_menu=3; else ae_menu=1; fi
    set_ctrl "auto_exposure" "$ae_menu" auto_exposure exposure_auto
fi

AWB="$(cfg auto_white_balance)"
[[ -n "$AWB" ]] && set_ctrl "auto_white_balance" "$AWB" white_balance_automatic white_balance_temperature_auto

FOCUS="$(cfg focus)"
[[ -n "$FOCUS" ]] && set_ctrl "focus" "$FOCUS" focus_absolute

EXP_MS="$(cfg exposure_ms)"
if [[ -n "$EXP_MS" ]]; then
    exp_units="$(awk -v ms="$EXP_MS" 'BEGIN { printf "%d", ms * 10 + 0.5 }')"  # V4L2 unit = 100 us
    set_ctrl "exposure_ms=$EXP_MS" "$exp_units" exposure_time_absolute exposure_absolute
fi

GAIN="$(cfg gain)"
[[ -n "$GAIN" ]] && set_ctrl "gain" "$GAIN" gain

WB_K="$(cfg white_balance_k)"
[[ -n "$WB_K" ]] && set_ctrl "white_balance_k" "$WB_K" white_balance_temperature

echo "== done: $APPLIED applied, $SKIPPED skipped. Check with: $0 $CAMERA --list =="
