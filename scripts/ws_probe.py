"""Check the core -> perception commands end to end (P1 dev tool): dialog_window (``to``), debug, calibrate, enroll.

    python scripts/ws_probe.py                 # own WS server on :8765, starts perception.main against it
    python scripts/ws_probe.py --no-calibrate  # skip the calibrate check (it starts a calibration run)

It does not touch core or port 8000: a temporary copy of perception.yaml points ``output.ws_url`` at this probe.
Every received frame is validated against the contract in use. Per command: PASS / FAIL with the acks received.
``calibrate`` / ``enroll`` use the throw-away profile ``ws-probe`` (deleted at the end); without a person in front
of the camera they end in ``error`` (no samples / no face), which still proves the ack chain. Nothing is recorded.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orjson  # noqa: E402
import yaml  # noqa: E402

from perception.config import REPO_ROOT  # noqa: E402
from perception.contract import validate_frame  # noqa: E402

PROFILE = "ws-probe"


def _kill_tree(pid: int) -> None:
    """Stop perception.main and its camera worker processes."""
    import psutil

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = [*parent.children(recursive=True), parent]
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            p.kill()
    psutil.wait_procs(procs, timeout=10)


class Probe:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        self.prompts: list[dict[str, Any]] = []
        self.invalid = 0
        self.ws: Any = None
        self.connected = asyncio.Event()

    async def handler(self, ws: Any) -> None:
        self.ws = ws
        self.connected.set()
        async for raw in ws:
            msg = orjson.loads(raw)
            kind = msg.get("type")
            if kind == "ack":
                self.acks.append(msg)
            elif kind == "calibration_prompt":
                self.prompts.append(msg)
            else:
                try:
                    validate_frame(msg)
                    self.frames.append(msg)
                except Exception:
                    self.invalid += 1

    async def send(self, cmd: dict[str, Any]) -> None:
        await self.ws.send(orjson.dumps({"type": "command", **cmd}).decode())

    async def acks_for(self, cmd: str, until: set[str], timeout: float) -> list[str]:
        """Statuses of ``cmd`` acks received since now, until one in ``until`` (or the timeout)."""
        start = len(self.acks)
        t_end = time.monotonic() + timeout
        while time.monotonic() < t_end:
            got = [a["status"] for a in self.acks[start:] if a.get("cmd") == cmd]
            if any(s in until for s in got):
                return got
            await asyncio.sleep(0.1)
        return [a["status"] for a in self.acks[start:] if a.get("cmd") == cmd]


async def run(port: int, calibrate: bool, seconds_warm: float) -> list[tuple[str, bool, str]]:
    import websockets

    probe = Probe()
    cfg = yaml.safe_load((REPO_ROOT / "perception/config/perception.yaml").read_text(encoding="utf-8"))
    cfg["output"]["ws_url"] = f"ws://localhost:{port}/ws/perception"
    tmp = Path(tempfile.mkdtemp(prefix="ws_probe_"))
    cfg_path = tmp / "perception.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    results: list[tuple[str, bool, str]] = []
    async with websockets.serve(probe.handler, "localhost", port):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "perception.main",
                "--no-mjpeg",
                "--config",
                str(cfg_path),
                "--log-level",
                "WARNING",
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(probe.connected.wait(), timeout=30)
            t_end = time.monotonic() + 40
            while time.monotonic() < t_end and not any(
                f["perf"]["cameras"].get("driver", {}).get("available") for f in probe.frames[-5:]
            ):
                await asyncio.sleep(0.2)
            await asyncio.sleep(seconds_warm)
            n0, t0 = len(probe.frames), time.monotonic()
            await asyncio.sleep(2.0)
            rate = (len(probe.frames) - n0) / (time.monotonic() - t0)
            cams = probe.frames[-1]["perf"]["cameras"] if probe.frames else {}
            up = sorted(c for c, v in cams.items() if v.get("available"))
            results.append(
                ("frames", rate >= 10 and probe.invalid == 0, f"{rate:.1f} Hz, invalid {probe.invalid}, up {up}")
            )

            await probe.send({"cmd": "debug", "on": True})
            got = await probe.acks_for("debug", {"ok", "error"}, 5)
            await probe.send({"cmd": "debug", "on": False})
            results.append(("debug", "ok" in got, f"acks {got}"))

            for to in ("driver", "passenger", 2):
                await probe.send({"cmd": "dialog_window", "open": True, "to": to, "until": time.time() + 3})
                got = await probe.acks_for("dialog_window", {"ok", "error"}, 5)
                results.append((f"dialog_window to={to}", "ok" in got, f"acks {got}"))

            await probe.send({"cmd": "enroll", "name": PROFILE, "camera": "passenger"})
            got = await probe.acks_for("enroll", {"done", "error"}, 75)
            results.append(("enroll camera=passenger", "started" in got and bool({"done", "error"} & set(got)),
                            f"acks {got}"))  # fmt: skip

            if calibrate:
                # full run (quick needs an existing profile): started + the first prompts prove the chain; the run
                # itself (~1 min, needs the driver to follow the prompts) is checked by scripts/calibrate.py
                await probe.send({"cmd": "calibrate", "profile": PROFILE})
                got = await probe.acks_for("calibrate", {"started", "error"}, 10)
                t_end = time.monotonic() + 10
                while not probe.prompts and time.monotonic() < t_end:
                    await asyncio.sleep(0.2)
                ok = "started" in got and bool(probe.prompts)
                first = probe.prompts[0].get("zone") if probe.prompts else None
                results.append(("calibrate", ok, f"acks {got}, first prompt zone={first}"))
        finally:
            _kill_tree(proc.pid)  # terminate() alone leaves the spawned camera workers holding the cameras (Windows)
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(REPO_ROOT / "profiles" / PROFILE, ignore_errors=True)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-calibrate", action="store_true")
    p.add_argument("--warm-s", type=float, default=2.0, help="wait after the driver camera is up")
    args = p.parse_args(argv)
    results = asyncio.run(run(args.port, not args.no_calibrate, args.warm_s))
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:28s} {detail}")
    return 0 if results and all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
