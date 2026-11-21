"""Which cameras are on this machine, on which USB controller, and which modes run on ALL of them at once.

    python scripts/camera_probe.py                       # devices + the default mode sets, 10 s each
    python scripts/camera_probe.py --seconds 20 --mode driver=1920x1080,passenger=1280x720

Why: two USB webcams on one laptop work only if the bus has room for both streams. Uncompressed YUY2 720p30 is
~55 MB/s per camera, so two cameras on one root hub fail or drop to a few fps; MJPG (compressed, requested at open
by perception/capture.py) needs a fraction of that. This script shows, on the laptop at hand (the demo laptop too):

1. every capture device with its USB id, serial, port and the ``usb:`` selector for perception.yaml;
2. on Windows, the PnP parent chain of each camera up to the USB root hub / host controller (two cameras on the same
   root hub share its bandwidth);
3. each mode set opened on all cameras SIMULTANEOUSLY through the runtime's own capture path
   (``LatestFrameCamera``), with the resolution, FOURCC and frame rate each camera really delivered.

Writes docs/benchmark/cameras-<hostname>.md. Never records images.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from perception.capture import CameraDevice, LatestFrameCamera, list_devices
from perception.config import REPO_ROOT, CameraConfig, load_config

OUT_DIR = REPO_ROOT / "docs" / "benchmark"
DEFAULT_MODES = (
    "driver=1280x720,passenger=1280x720",
    "driver=1920x1080,passenger=1280x720",
)


@dataclass
class CamRun:
    name: str
    requested: str
    delivered: str = "-"
    fourcc: str = "-"
    fps: float = 0.0
    frames: int = 0
    dropped: int = 0
    reconnects: int = 0
    error: str | None = None


def selector(d: CameraDevice, devices: list[CameraDevice]) -> str:
    """The shortest usb: selector that names exactly this device."""
    if d.vid is None or d.pid is None:
        return str(d.index)
    base = f"usb:{d.vid}:{d.pid}"
    twins = [o for o in devices if o.vid == d.vid and o.pid == d.pid]
    if len(twins) == 1:
        return base
    if d.serial:
        return f"{base}:{d.serial}"
    return f"{base}@{d.port.split('&')[-1]}" if d.port else base


def _pnp_instance(path: str) -> str | None:
    """DirectShow device path -> PnP instance id of its USB interface (USB/VID_../7&D60E892&0&0002, backslashes)."""
    low = path.lower()
    if "usb#" not in low:
        return None
    parts = path.split("#")
    if len(parts) < 3:
        return None
    return f"USB\\{parts[1]}\\{parts[2]}".upper()


def usb_chain(instance: str, depth: int = 6) -> list[dict[str, str]]:
    """Windows only: the PnP parents of ``instance`` (interface -> composite device -> hub -> ... -> controller)."""
    script = (
        "$id = '" + instance.replace("'", "''") + "'; $out = @(); "
        f"for ($i = 0; $i -lt {depth} -and $id; $i++) {{ "
        "$d = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue; "
        "$loc = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_LocationInfo "
        "-ErrorAction SilentlyContinue).Data; "
        "$out += [pscustomobject]@{ id = $id; name = [string]$d.FriendlyName; location = [string]$loc }; "
        "$id = (Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Parent "
        "-ErrorAction SilentlyContinue).Data }; $out | ConvertTo-Json -Compress"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(res.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    rows = data if isinstance(data, list) else [data]
    return [{k: str(r.get(k) or "") for k in ("id", "name", "location")} for r in rows]


def root_hub(chain: list[dict[str, str]]) -> str | None:
    for row in chain:
        if "ROOT_HUB" in row["id"].upper():
            return row["id"]
    return None


def parse_mode(text: str) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for part in text.split(","):
        name, _, size = part.partition("=")
        w, _, h = size.lower().partition("x")
        out[name.strip()] = (int(w), int(h))
    return out


def run_mode(cams: dict[str, CameraConfig], mode: dict[str, tuple[int, int]], seconds: float) -> list[CamRun]:
    """Open every camera of ``mode`` at once, let them settle, then count frames for ``seconds``."""
    runs: dict[str, CamRun] = {}
    opened: dict[str, LatestFrameCamera] = {}
    try:
        for name, (w, h) in mode.items():
            cfg = cams[name].model_copy(update={"width": w, "height": h})
            runs[name] = CamRun(name, f"{w}x{h} {cfg.fourcc or '-'} @{cfg.fps:g}")
            opened[name] = LatestFrameCamera(cfg, name).start()  # opens in its reader thread
        for name, cam in opened.items():
            if cam.wait_new(0, timeout=10.0) is None:
                runs[name].error = "no frame within 10 s (device busy, missing, or the bus is full)"
        time.sleep(2.0)  # exposure / first frames
        start = {n: c.stats() for n, c in opened.items()}
        t0 = time.perf_counter()
        time.sleep(seconds)
        elapsed = time.perf_counter() - t0
        for name, cam in opened.items():
            st, st0, run = cam.stats(), start[name], runs[name]
            run.frames = st.frames - st0.frames
            run.fps = round(run.frames / elapsed, 1)
            run.dropped = st.dropped - st0.dropped
            run.reconnects = st.reconnects
            if st.info is not None:
                run.delivered = f"{st.info.width}x{st.info.height}"
                run.fourcc = st.info.fourcc
            if not st.connected:
                run.error = "disconnected during the run"
    finally:
        for cam in opened.values():
            cam.stop()
    return list(runs.values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--seconds", type=float, default=10.0, help="measurement time per mode set")
    p.add_argument("--mode", action="append", default=None, help="driver=WxH,passenger=WxH (repeatable)")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    cams = {"driver": cfg.cameras.driver, "passenger": cfg.cameras.passenger}
    host = socket.gethostname()
    devices = list_devices()

    lines = [
        f"# Cameras on {host}, {dt.date.today().isoformat()}",
        "",
        "Generated by `scripts/camera_probe.py`. Mode sets are opened on all cameras at the same time through the "
        "runtime capture path (`LatestFrameCamera`, FOURCC requested at open), 2 s settle, then frames counted.",
        "",
        "## Devices",
        "",
        "| index | name | vid:pid | serial | port | selector for perception.yaml | root hub |",
        "|---|---|---|---|---|---|---|",
    ]
    chains: dict[int, list[dict[str, str]]] = {}
    for d in devices:
        inst = _pnp_instance(d.path) if sys.platform == "win32" else None
        chains[d.index] = usb_chain(inst) if inst else []
        hub = root_hub(chains[d.index]) or "-"
        lines.append(
            f"| {d.index} | {d.name} | {d.vid}:{d.pid} | {d.serial or '-'} | {d.port or '-'} | "
            f"`{selector(d, devices)}` | {hub} |"
        )
        print(f"{d.index}: {d.name} {d.vid}:{d.pid} port={d.port} -> {selector(d, devices)} (hub {hub})")
    hubs = [h for h in (root_hub(c) for c in chains.values()) if h is not None]
    shared = {h for h in hubs if hubs.count(h) > 1}
    if shared:
        lines += ["", f"Cameras sharing a root hub (shared bandwidth): {', '.join(sorted(shared))}."]
    for d in devices:
        if chains.get(d.index):
            lines += ["", f"### {d.index}: {d.name}, USB chain", ""]
            lines += [f"- {r['name'] or '?'} ({r['location'] or '-'}): `{r['id']}`" for r in chains[d.index]]

    lines += [
        "",
        "## Simultaneous capture",
        "",
        f"Configured: driver `{cams['driver'].device}`, passenger `{cams['passenger'].device}` (enabled: "
        f"{cams['passenger'].enabled}).",
        "",
        "| mode set | camera | requested | delivered | fourcc | fps | dropped | reconnects | error |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for text in args.mode or DEFAULT_MODES:
        mode = parse_mode(text)
        print(f"mode {text} ...", flush=True)
        for r in run_mode(cams, mode, args.seconds):
            lines.append(
                f"| {text} | {r.name} | {r.requested} | {r.delivered} | {r.fourcc} | {r.fps} | {r.dropped} | "
                f"{r.reconnects} | {r.error or ''} |"
            )
            print(f"  {r.name}: {r.delivered} {r.fourcc} {r.fps} fps {r.error or ''}")
    lines.append("")
    out = args.out or OUT_DIR / f"cameras-{host}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
