"""The SOS to the emergency contact through Twilio (F6): a voice call that says the driver's state, and an SMS with the
location. P2. Phone numbers and keys live only in ``.env``:

    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER   (the Twilio account and its number)
    EMERGENCY_NUMBER                                             (who is called; NEVER 112 in a demo)
    TWILIO_VOICE (optional)                                      (the Twilio <Say> voice, default sos.call_voice)

The text is core's fixed template (``templates.yaml`` ``sos.call`` / ``sos.sms``, filled in ``SosReport``): no LLM on
this path. Twilio dials the number; when it is answered it reads the text (TwiML ``<Say>``, Romanian), twice. No public
server is needed: the TwiML goes with the request.

Every function blocks (network): core runs them in a background thread (``core/safety/channels.py``). They never
raise; they return a short status: ``answered``, ``no_answer``, ``busy``, ``failed``, ``sent``, ``not_connected`` or
``error: ...``.

**Tests never call anyone**: under pytest the module reports ``not_connected`` unless ``DRIVEMATE_TWILIO_LIVE=1``
(the ``.env`` with the real keys is loaded by the tests too).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from xml.sax.saxutils import escape

from shared.contracts import SosReport

log = logging.getLogger("drivemate.integrations.twilio")

#: Twilio call statuses that end a call (https://www.twilio.com/docs/voice/api/call-resource#call-status-values).
FINAL_STATUSES = frozenset({"completed", "busy", "failed", "no-answer", "canceled"})


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def configured() -> bool:
    """Keys, the Twilio number and the emergency number are set, and this is not a test run."""
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("DRIVEMATE_TWILIO_LIVE"):
        return False
    return all(_env(name) for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
                                       "EMERGENCY_NUMBER"))


def _client() -> Any:
    from twilio.rest import Client  # here: core runs without the twilio package (the channel is then not_connected)

    return Client(_env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"))


def build_twiml(text: str, voice: str, language: str = "ro-RO", repeat: int = 2, pause_s: int = 1) -> str:
    """The TwiML read to the person who answers: ``text`` ``repeat`` times, a pause between, escaped for XML."""
    say = f'<Say voice="{escape(voice)}" language="{escape(language)}">{escape(text)}</Say>'
    parts = [say if i == 0 else f'<Pause length="{pause_s}"/>{say}' for i in range(max(1, repeat))]
    return f"<Response>{''.join(parts)}</Response>"


def place_sos_call(report: SosReport, *, voice: str, repeat: int = 2, ring_s: int = 30, wait_s: float = 75.0,
                   poll_s: float = 2.0) -> str:
    """Call the emergency contact, read ``report.call_text``, and wait for the outcome (up to ``wait_s``).

    Returns ``answered`` (the person picked up and heard it), ``no_answer``, ``busy``, ``failed``, ``started`` (still
    ringing after ``wait_s``), ``not_connected`` or ``error: ...``.
    """
    if not configured():
        return "not_connected"
    try:
        client = _client()
        params = {"to": _env("EMERGENCY_NUMBER"), "from_": _env("TWILIO_FROM_NUMBER"),
                  "twiml": build_twiml(report.call_text or report.text, _env("TWILIO_VOICE") or voice, repeat=repeat)}
        try:
            call = client.calls.create(timeout=ring_s, **params)
        except Exception as exc:
            if "trial accounts" not in str(exc).lower():
                raise
            # A trial account refuses the optional parameters (timeout): call with the required ones (rings ~60 s).
            log.info("Twilio trial account: calling without the ring timeout")
            call = client.calls.create(**params)
        log.info("SOS call placed: %s", call.sid)
        deadline = time.monotonic() + wait_s
        status = str(call.status)
        answered = False
        while status not in FINAL_STATUSES and time.monotonic() < deadline:
            time.sleep(poll_s)
            status = str(client.calls(call.sid).fetch().status)
            answered = answered or status == "in-progress"
        if status == "completed" or answered:
            return "answered"
        return {"no-answer": "no_answer", "busy": "busy", "failed": "failed", "canceled": "failed"}.get(status,
                                                                                                         "started")
    except Exception as exc:  # network, auth, a refused number (trial: not verified / geo permission)
        log.warning("SOS call failed: %s", exc)
        return f"error: {exc.__class__.__name__}: {str(exc)[:160]}"


def send_sms(text: str) -> str:
    """Send ``text`` to the emergency contact. Returns ``sent``, ``not_connected`` or ``error: ...``."""
    if not configured():
        return "not_connected"
    try:
        message = _client().messages.create(to=_env("EMERGENCY_NUMBER"), from_=_env("TWILIO_FROM_NUMBER"), body=text)
        log.info("SMS sent: %s", message.sid)
        return "sent"
    except Exception as exc:
        log.warning("SMS failed: %s", exc)
        return f"error: {exc.__class__.__name__}: {str(exc)[:160]}"


def send_sos_sms(report: SosReport) -> str:
    """The SOS SMS (``report.text``: the state and the map link)."""
    return send_sms(report.text)
