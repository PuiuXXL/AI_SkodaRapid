"""The SOS to the emergency contact through Telegram (F6), free: a message with the state, the location and a voice
note from our own bot, and a Telegram voice call that reads the state (CallMeBot). P2. Keys live only in ``.env``:

    TELEGRAM_BOT_TOKEN   the bot made with @BotFather (/newbot)
    TELEGRAM_CHAT_ID     the contact's chat with the bot (the contact presses Start; scripts/telegram_check.py --chat-id
                         prints it)
    TELEGRAM_CALL_USER   the contact's Telegram @username, for the call (the contact sends /start to @CallMeBot_txtbot
                         once, to allow it)

The bot is the official Telegram Bot API (``api.telegram.org``). The call goes through CallMeBot
(https://www.callmebot.com), a free third-party service that rings the contact's Telegram and reads a short text
(256 characters at most) with a Google voice; it cannot tell whether the call was answered (status ``started``). The
texts are core's fixed templates (``templates.yaml`` ``sos``): no LLM on this path.

Every function blocks (network): core runs them in a background thread (``core/safety/channels.py``). They never raise;
they return a short status: ``sent``, ``started``, ``not_connected`` or ``error: ...``. The bot token never reaches the
log: errors are cleaned of it and httpx's request log is turned down.

**Tests never send anything**: under pytest the module reports ``not_connected`` unless ``DRIVEMATE_TELEGRAM_LIVE=1``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

from shared.contracts import SosReport

log = logging.getLogger("drivemate.integrations.telegram")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO line has the URL, and the URL has the bot token

API_URL = "https://api.telegram.org/bot{token}/{method}"
CALL_URL = "https://api.callmebot.com/start.php"
CALL_MAX_CHARS = 256  # CallMeBot cuts longer texts
TIMEOUT_S = 20.0


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _live() -> bool:
    return not (os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("DRIVEMATE_TELEGRAM_LIVE"))


def bot_configured() -> bool:
    """The bot token and the contact's chat are set, and this is not a test run."""
    return _live() and bool(_env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"))


def call_configured() -> bool:
    """The contact's @username for the CallMeBot call is set, and this is not a test run."""
    return _live() and bool(_env("TELEGRAM_CALL_USER"))


def _http() -> Any:
    import httpx  # here: core runs without httpx (the channel is then an error, not a crash)

    return httpx.Client(timeout=TIMEOUT_S)


def _clean(exc: BaseException) -> str:
    """An error string without the bot token (httpx puts the URL in its messages)."""
    text = f"{exc.__class__.__name__}: {exc}"
    token = _env("TELEGRAM_BOT_TOKEN")
    if token:
        text = text.replace(token, "***")
    return text[:200]


def _bot(method: str, *, data: dict[str, Any], files: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a Bot API method; raises RuntimeError with Telegram's description when it says no."""
    with _http() as http:
        response = http.post(API_URL.format(token=_env("TELEGRAM_BOT_TOKEN"), method=method), data=data, files=files)
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('error_code')} {body.get('description')}")
    return body


def send_message(text: str) -> str:
    """Send ``text`` to the contact's chat. Returns ``sent``, ``not_connected`` or ``error: ...``."""
    if not bot_configured():
        return "not_connected"
    try:
        _bot("sendMessage", data={"chat_id": _env("TELEGRAM_CHAT_ID"), "text": text})
        log.info("Telegram message sent")
        return "sent"
    except Exception as exc:  # network, a wrong token, a chat that never pressed Start
        log.warning("Telegram message failed: %s", _clean(exc))
        return f"error: {_clean(exc)}"


def send_location(lat: float, lon: float) -> str:
    """A map pin the contact can open in the navigation app."""
    if not bot_configured():
        return "not_connected"
    try:
        _bot("sendLocation", data={"chat_id": _env("TELEGRAM_CHAT_ID"), "latitude": lat, "longitude": lon})
        return "sent"
    except Exception as exc:
        log.warning("Telegram location failed: %s", _clean(exc))
        return f"error: {_clean(exc)}"


def voice_mp3(text: str) -> bytes:
    """The text in the assistant's Romanian voice (edge-tts, needs internet), as mp3 bytes."""
    from assistant.tts import synthesize

    return asyncio.run(synthesize(text))


def send_voice(text: str) -> str:
    """A voice note that says ``text`` (a voice message bubble in Telegram)."""
    if not bot_configured():
        return "not_connected"
    try:
        audio = voice_mp3(text)
        _bot("sendVoice", data={"chat_id": _env("TELEGRAM_CHAT_ID")},
             files={"voice": ("drivemate_sos.mp3", audio, "audio/mpeg")})
        return "sent"
    except Exception as exc:
        log.warning("Telegram voice note failed: %s", _clean(exc))
        return f"error: {_clean(exc)}"


def send_sos_message(report: SosReport) -> str:
    """The SOS message: the state with the map link, a map pin, and the state read aloud (voice note).

    The status is the text's: the pin and the voice note are extras (their failures are only logged).
    """
    status = send_message(report.text)
    if status != "sent":
        return status
    pos = report.pos
    if pos is not None and (pos.lat or pos.lon):
        send_location(pos.lat, pos.lon)
    if report.call_text:
        send_voice(report.call_text)
    return status


def short_text(text: str, limit: int = CALL_MAX_CHARS) -> str:
    """``text`` cut at a word to ``limit`` characters (CallMeBot reads at most 256)."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "."


def page_text(html: str) -> str:
    """The visible text of CallMeBot's answer page (no scripts, no styles, no tags)."""
    html = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def place_call(text: str, *, lang: str, repeat: int = 2, attempts: int = 3, retry_s: float = 70.0) -> str:
    """Ring the contact's Telegram and read ``text`` (CallMeBot). Returns ``started``, ``not_connected`` or ``error``.

    CallMeBot's free bot skips calls when it is busy ("Error: FLOOD - Too many users making calls"): the call is then
    asked again, up to ``attempts`` times, ``retry_s`` apart (more than 65 s: it refuses two calls to the same user
    within 65 seconds, and that refusal is waited out too). Whether the contact picked up is not known.
    """
    if not call_configured():
        return "not_connected"
    user = _env("TELEGRAM_CALL_USER")
    user = user if user.startswith(("@", "+")) else "@" + user
    status = "error: no attempt"
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with _http() as http:
                response = http.get(CALL_URL, params={"user": user, "text": short_text(text), "lang": lang,
                                                      "rpt": repeat, "cc": "no"})
            page = page_text(response.text)
        except Exception as exc:
            log.warning("Telegram call failed: %s", _clean(exc))
            status = f"error: {_clean(exc)}"
        else:
            if response.status_code == 200 and not re.search(r"\berror\b|not authori[sz]ed", page, re.IGNORECASE):
                log.info("Telegram call placed (attempt %d): %s", attempt, page[-200:])
                return "started"
            found = re.search(r"Error:.*", page)
            status = f"error: {response.status_code} {(found.group(0) if found else page)[:200]}"
            log.warning("Telegram call refused (attempt %d): %s", attempt, page[:600])
            if "FLOOD" not in page.upper() and "WITHIN 65 SECONDS" not in page.upper():
                return status  # not busy: asking again will not help
        if attempt < attempts:
            time.sleep(retry_s)
    return status


def chats() -> list[dict[str, Any]]:
    """The chats that wrote to the bot lately (getUpdates): to find the contact's ``TELEGRAM_CHAT_ID``."""
    body = _bot("getUpdates", data={})
    seen: dict[int, dict[str, Any]] = {}
    for update in body.get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            seen[chat["id"]] = {"id": chat["id"], "username": chat.get("username"),
                                "name": " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p)}
    return list(seen.values())
