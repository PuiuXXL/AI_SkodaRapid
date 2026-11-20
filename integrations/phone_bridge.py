"""Bridge between the driver's Android phone (KDE Connect) and core (plan F1, F3, F6, F8).

Runs as a **separate process** (roluri/P3 step 5), possibly on another Linux laptop
when the demo laptop runs Windows (plan decision 9): it only needs ``CORE_URL``.

What it does:

* listens on the session D-Bus for new notifications of the paired phone
  (KDE Connect ``notificationPosted`` signal), keeps only whitelisted apps
  (SMS, WhatsApp) and senders (``phone.app_whitelist`` / ``phone.contact_whitelist``
  in assistant.yaml) and sends them to core as ``phone_message``;
* executes core's commands:

  - ``send_reply``: answers a notification through its reply action
    (``sendReply`` - works for WhatsApp and for SMS apps with direct reply);
  - ``send_sms``: ``kdeconnect-cli --send-sms`` to the trusted contact or the
    emergency number (plan F6, F8). Core names the **role** (``safe_contact`` /
    ``emergency``); the numbers are read here from ``.env`` and never travel or get
    logged (plan decision 10);

* reports ``phone_status`` (connected, battery) every ``phone.status_interval_s``.

Messages on ``/ws/phone`` (P3 proposal, documented in docs/assistant.md)::

    bridge -> core  {"type": "phone_message", "notification_id": "...", "app": "whatsapp",
                     "from": "Mihai", "text": "...", "replyable": true, "ts": 1763672390.0}
    bridge -> core  {"type": "phone_status", "connected": true, "battery": 64}
    bridge -> core  {"type": "phone_result", "request_id": "...", "ok": true, "error": null}
    core -> bridge  {"type": "send_reply", "request_id": "...", "notification_id": "...", "text": "..."}
    core -> bridge  {"type": "send_sms", "request_id": "...", "to": "safe_contact", "text": "..."}

Requirements (plan F, "Condiții pentru F1/F3"): Linux with KDE Connect installed and
paired with an **Android** phone (iPhone is not supported), notification access
granted on the phone, both on the same network (phone hotspot / USB tethering if
the venue Wi-Fi isolates devices), ``dbus-next`` installed.

Usage::

    python integrations/phone_bridge.py                 # real bridge (Linux)
    python integrations/phone_bridge.py --dry-run       # any OS: no D-Bus, nothing sent;
                                                        # type "Mihai|Salut!" to fake a message
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import websockets  # noqa: E402

from assistant.settings import cfg  # noqa: E402  (also loads .env)

log = logging.getLogger("drivemate.phone_bridge")

KDE_SERVICE = "org.kde.kdeconnect"
NOTIFICATIONS_IFACE = "org.kde.kdeconnect.device.notifications"
NOTIFICATION_IFACE = "org.kde.kdeconnect.device.notifications.notification"
BATTERY_IFACE = "org.kde.kdeconnect.device.battery"
DEVICE_IFACE = "org.kde.kdeconnect.device"

#: ``send_sms`` roles -> .env variable holding the number.
SMS_ROLES = {"safe_contact": "SAFE_CONTACT_NUMBER", "emergency": "EMERGENCY_NUMBER"}


def core_ws_url() -> str:
    """``CORE_URL`` from .env (``http://host:8000``) turned into ``ws://host:8000/ws/phone``."""
    base = os.getenv("CORE_URL", "http://localhost:8000").rstrip("/")
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/ws/phone"


def classify(app_name: str, sender: str, text: str) -> Optional[str]:
    """Return the contract app code (``sms`` / ``whatsapp``) if the notification is accepted.

    Rejects: apps not in ``phone.app_whitelist``; senders not in
    ``phone.contact_whitelist`` (unless it is ``["*"]``); summary notifications
    such as "WhatsApp: 3 new messages" (title equal to the app name, or empty text).

    Args:
        app_name: Android app name reported by KDE Connect.
        sender: Notification title (the contact name for messaging apps).
        text: Notification body.

    Returns:
        The app code, or None if the notification must be ignored.
    """
    app = (cfg("phone", "app_whitelist", default={}) or {}).get(app_name)
    if app is None or not text or not sender or sender == app_name:
        return None
    contacts = cfg("phone", "contact_whitelist", default=["*"]) or ["*"]
    if "*" not in contacts and sender not in contacts:
        return None
    return app


class CoreLink:
    """WebSocket connection to core with automatic reconnection and an outgoing queue."""

    def __init__(self, url: str, on_command) -> None:
        """Args:
            url: ``ws://.../ws/phone``.
            on_command: ``async (dict) -> None`` called for every message from core.
        """
        self.url = url
        self.on_command = on_command
        self.outbox: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
        self.connected = False

    def send(self, message: dict[str, Any]) -> None:
        """Queue a message for core (dropped with a warning if the queue is full)."""
        try:
            self.outbox.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("outbox full, dropping %s", message.get("type"))

    async def run(self) -> None:
        """Connect, pump messages both ways, reconnect forever."""
        delay = float(cfg("phone", "reconnect_s", default=3))
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    self.connected = True
                    log.info("connected to core at %s", self.url)
                    await asyncio.gather(self._sender(ws), self._receiver(ws))
            except (OSError, websockets.WebSocketException) as exc:
                if self.connected:
                    log.warning("lost core connection: %s", exc)
                else:
                    log.info("core not reachable at %s (%s); retrying in %.0fs", self.url, exc, delay)
            self.connected = False
            await asyncio.sleep(delay)

    async def _sender(self, ws) -> None:
        """Forward queued messages to core."""
        while True:
            message = await self.outbox.get()
            await ws.send(json.dumps(message, ensure_ascii=False))

    async def _receiver(self, ws) -> None:
        """Dispatch commands from core."""
        async for raw in ws:
            try:
                await self.on_command(json.loads(raw))
            except Exception:  # noqa: BLE001 - a bad command must not kill the bridge
                log.exception("command failed: %s", raw)


class PhoneBridge:
    """The bridge itself: D-Bus side (real) or console side (``--dry-run``)."""

    def __init__(self, device_id: str, dry_run: bool = False) -> None:
        """Args:
            device_id: KDE Connect device id (``KDECONNECT_DEVICE_ID``).
            dry_run: True = no D-Bus, no SMS; print actions and accept fake messages from stdin.
        """
        self.device_id = device_id
        self.dry_run = dry_run
        self.device_path = f"/modules/kdeconnect/devices/{device_id}"
        self.bus = None
        self.core = CoreLink(core_ws_url(), self.handle_command)

    # ------------------------------------------------------------------ phone -> core

    async def connect_dbus(self) -> None:
        """Subscribe to ``notificationPosted`` on the session bus (Linux only)."""
        from dbus_next.aio import MessageBus  # Linux-only dependency, imported lazily

        self.bus = await MessageBus().connect()
        path = f"{self.device_path}/notifications"
        introspection = await self.bus.introspect(KDE_SERVICE, path)
        notifications = self.bus.get_proxy_object(KDE_SERVICE, path, introspection).get_interface(NOTIFICATIONS_IFACE)
        notifications.on_notification_posted(
            lambda public_id: asyncio.ensure_future(self.on_notification(public_id)))
        log.info("listening for notifications of device %s", self.device_id)

    async def _notification_iface(self, public_id: str):
        """D-Bus interface of one notification object."""
        path = f"{self.device_path}/notifications/{public_id}"
        introspection = await self.bus.introspect(KDE_SERVICE, path)
        return self.bus.get_proxy_object(KDE_SERVICE, path, introspection).get_interface(NOTIFICATION_IFACE)

    async def on_notification(self, public_id: str) -> None:
        """Read a new notification, filter it and forward it to core."""
        try:
            iface = await self._notification_iface(public_id)
            app_name = await iface.get_app_name()
            sender = await iface.get_title()
            text = await iface.get_text()
            try:
                reply_id = await iface.get_reply_id()
            except Exception:  # noqa: BLE001 - property missing on old KDE Connect versions
                reply_id = ""
        except Exception as exc:  # noqa: BLE001 - notification vanished, D-Bus error
            log.warning("cannot read notification %s: %s", public_id, exc)
            return
        self.forward(public_id, app_name, sender, text, bool(reply_id))

    def forward(self, notification_id: str, app_name: str, sender: str, text: str, replyable: bool) -> None:
        """Send an accepted notification to core as ``phone_message``."""
        app = classify(app_name, sender, text)
        if app is None:
            log.debug("ignored notification from %s (%s)", app_name, sender)
            return
        log.info("message from %s via %s", sender, app)  # never log the text
        self.core.send({
            "type": "phone_message", "notification_id": notification_id, "app": app,
            "from": sender, "text": text, "replyable": replyable, "ts": time.time(),
        })

    async def status_loop(self) -> None:
        """Report connection and battery to core periodically (state ``phone``)."""
        interval = float(cfg("phone", "status_interval_s", default=30))
        while True:
            self.core.send({"type": "phone_status", **(await self.read_status())})
            await asyncio.sleep(interval)

    async def read_status(self) -> dict[str, Any]:
        """Phone reachability and battery charge (None when unknown)."""
        if self.dry_run or self.bus is None:
            return {"connected": not self.dry_run and self.bus is not None, "battery": None}
        status: dict[str, Any] = {"connected": False, "battery": None}
        try:
            intro = await self.bus.introspect(KDE_SERVICE, self.device_path)
            device = self.bus.get_proxy_object(KDE_SERVICE, self.device_path, intro).get_interface(DEVICE_IFACE)
            status["connected"] = bool(await device.get_is_reachable())
            path = f"{self.device_path}/battery"
            intro = await self.bus.introspect(KDE_SERVICE, path)
            battery = self.bus.get_proxy_object(KDE_SERVICE, path, intro).get_interface(BATTERY_IFACE)
            status["battery"] = int(await battery.get_charge())
        except Exception as exc:  # noqa: BLE001 - plugin disabled / older KDE Connect
            log.debug("status read failed: %s", exc)
        return status

    # ------------------------------------------------------------------ core -> phone

    async def handle_command(self, message: dict[str, Any]) -> None:
        """Execute ``send_reply`` / ``send_sms`` from core and report ``phone_result``."""
        kind = message.get("type")
        request_id = message.get("request_id")
        try:
            if kind == "send_reply":
                await self.send_reply(str(message["notification_id"]), str(message["text"]))
            elif kind == "send_sms":
                await self.send_sms(str(message["to"]), str(message["text"]))
            else:
                return
            self.core.send({"type": "phone_result", "request_id": request_id, "ok": True, "error": None})
        except Exception as exc:  # noqa: BLE001 - report every failure to core
            log.warning("%s failed: %s", kind, exc)
            self.core.send({"type": "phone_result", "request_id": request_id, "ok": False, "error": str(exc)})

    async def send_reply(self, notification_id: str, text: str) -> None:
        """Reply through the notification's reply action (plan F3, WhatsApp ``sendReply``)."""
        if self.dry_run:
            print(f"[dry-run] sendReply to notification {notification_id}: {text}")
            return
        iface = await self._notification_iface(notification_id)
        await iface.call_send_reply(text)
        log.info("reply sent to notification %s", notification_id)

    async def send_sms(self, role: str, text: str) -> None:
        """Send an SMS from the driver's phone to a configured role (plan F6, F8).

        Args:
            role: ``safe_contact`` or ``emergency`` (numbers come from .env).
            text: The message (fixed template from P2, e.g. the SOS report).

        Raises:
            ValueError: Unknown role or number missing in .env.
            RuntimeError: ``kdeconnect-cli`` missing or failed.
        """
        env_name = SMS_ROLES.get(role)
        if env_name is None:
            raise ValueError(f"unknown SMS role {role!r} (allowed: {', '.join(SMS_ROLES)})")
        number = os.getenv(env_name, "").strip()
        if not number:
            raise ValueError(f"{env_name} is empty in .env")
        if self.dry_run:
            print(f"[dry-run] SMS to {role} ({env_name}): {text}")
            return
        cli = shutil.which("kdeconnect-cli")
        if cli is None:
            raise RuntimeError("kdeconnect-cli not found")
        process = await asyncio.create_subprocess_exec(
            cli, "-d", self.device_id, "--send-sms", text, "--destination", number,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"kdeconnect-cli exit {process.returncode}: {stderr.decode(errors='replace').strip()}")
        log.info("SMS sent to %s", role)

    # ------------------------------------------------------------------ dry-run input

    async def console_loop(self) -> None:
        """Dry-run: read ``Sender|text`` lines from the keyboard and forward them as WhatsApp messages."""
        loop = asyncio.get_running_loop()
        print('Dry-run: type "Sender|message text" and Enter to fake a WhatsApp message (Ctrl+C to quit).')
        counter = 0
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            if "|" not in line:
                continue
            sender, text = (part.strip() for part in line.split("|", 1))
            counter += 1
            self.forward(f"fake-{counter}", "WhatsApp", sender, text, replyable=True)
            print(f"[dry-run] forwarded fake-{counter} from {sender} (core connected: {self.core.connected})")

    async def run(self) -> None:
        """Start everything and run forever."""
        tasks = [self.core.run(), self.status_loop()]
        if self.dry_run:
            tasks.append(self.console_loop())
        else:
            await self.connect_dbus()
        await asyncio.gather(*tasks)


async def detect_device_id() -> str:
    """``KDECONNECT_DEVICE_ID`` from .env, or the first device listed by ``kdeconnect-cli``."""
    device_id = os.getenv("KDECONNECT_DEVICE_ID", "").strip()
    if device_id or shutil.which("kdeconnect-cli") is None:
        return device_id
    process = await asyncio.create_subprocess_exec(
        "kdeconnect-cli", "-l", "--id-only", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await process.communicate()
    ids = out.decode().split()
    return ids[0] if ids else ""


async def amain(dry_run: bool) -> None:
    """Async entry point."""
    device_id = "dry-run" if dry_run else await detect_device_id()
    if not device_id:
        raise SystemExit("No KDE Connect device: pair the phone and set KDECONNECT_DEVICE_ID in .env "
                         "(see `kdeconnect-cli -l`).")
    await PhoneBridge(device_id, dry_run=dry_run).run()


def main() -> None:
    """Command-line entry point (see module docstring)."""
    # Windows consoles default to cp1252, which cannot print Romanian diacritics.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="DriveMate phone bridge (KDE Connect <-> core).")
    parser.add_argument("--dry-run", action="store_true", help="no D-Bus, nothing sent; fake messages from stdin")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        asyncio.run(amain(args.dry_run))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
