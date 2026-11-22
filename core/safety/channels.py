"""The SOS channels that talk to the network, run in the background (F6).

A channel is ``report -> status``; one that talks to the network must not block the engine (alarms, the countdown and
the answers keep running). :func:`in_background` wraps such a function: the channel returns a ``Future`` at once and
``SosMachine`` reports the outcome when it is done (event ``sos_channel_result``, and a sentence in the car for the
call).

The Twilio channels (``integrations/twilio_call.py``): ``call`` = a voice call to the emergency contact that reads the
state (``SosReport.call_text``), ``sms`` = the state + the map link. Both are ``not_connected`` (synchronously, no
Future) when Twilio is not set up in ``.env`` or under pytest.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from core.settings import th
from shared.contracts import SosReport

log = logging.getLogger("drivemate.core.sos_channels")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sos")


def in_background(fn: Callable[[], str]) -> Future[str]:
    """Run ``fn`` in the SOS thread pool; the Future always ends with a status string (never an exception)."""

    def safe() -> str:
        try:
            return str(fn())
        except Exception as exc:  # a channel must never break the SOS
            log.exception("SOS channel failed")
            return f"error: {exc.__class__.__name__}"

    return _executor.submit(safe)


def _twilio() -> Any | None:
    try:
        from integrations import twilio_call
    except Exception:  # noqa: BLE001 - core runs without the integration
        return None
    return twilio_call


def twilio_call_channel(report: SosReport) -> str | Future[str]:
    """``call``: the emergency contact hears the state (two times), in Romanian."""
    twilio = _twilio()
    if twilio is None or not twilio.configured():
        return "not_connected"
    voice, repeat = str(th("sos", "call_voice")), int(th("sos", "call_repeat"))
    return in_background(lambda: twilio.place_sos_call(report, voice=voice, repeat=repeat))


def twilio_sms_channel(report: SosReport) -> str | Future[str]:
    """``sms``: the state and the map link."""
    twilio = _twilio()
    if twilio is None or not twilio.configured():
        return "not_connected"
    return in_background(lambda: twilio.send_sos_sms(report))


def twilio_all_clear(text: str) -> str | Future[str]:
    """The driver answered after the SOS went out: tell the emergency contact (SMS)."""
    twilio = _twilio()
    if twilio is None or not twilio.configured():
        return "not_connected"
    return in_background(lambda: twilio.send_sms(text))
