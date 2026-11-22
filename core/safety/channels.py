"""The SOS channels that talk to the network, run in the background (F6).

A channel is ``report -> status``; one that talks to the network must not block the engine (alarms, the countdown and
the answers keep running). :func:`in_background` wraps such a function: the channel returns a ``Future`` at once and
``SosMachine`` reports the outcome when it is done (event ``sos_channel_result``, and a sentence in the car for the
call).

Two providers, chosen per channel from what ``.env`` sets up, **Telegram first** (free), Twilio otherwise:

* ``call``: Telegram = the contact's Telegram rings and a voice reads a short state (CallMeBot,
  ``integrations/telegram_alert.py``); Twilio = a phone call that reads the state (``integrations/twilio_call.py``,
  a paid account: the trial one refuses our text).
* ``sms``: Telegram = our bot sends the state with the map link, a map pin and a voice note; Twilio = an SMS.

A channel with no provider set up (or under pytest) is ``not_connected``, synchronously (no Future).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from core.settings import render, th
from shared.contracts import SosReport

log = logging.getLogger("drivemate.core.sos_channels")
logging.getLogger("twilio.http_client").setLevel(logging.WARNING)  # one INFO line per header, the account in the URL

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


def _module(name: str) -> Any | None:
    try:
        if name == "telegram":
            from integrations import telegram_alert as module
        else:
            from integrations import twilio_call as module
    except Exception:  # noqa: BLE001 - core runs without the integrations
        return None
    return module


def call_text_short(report: SosReport) -> str:
    """The short state read in the Telegram call (CallMeBot reads at most 256 characters)."""
    return render("sos", "call_short", driver_name=report.driver_name, unresponsive_s=round(report.unresponsive_s),
                  cause=report.cause)


def call_channel(report: SosReport) -> str | Future[str]:
    """``call``: the emergency contact hears the state (two times), in Romanian."""
    telegram = _module("telegram")
    if telegram is not None and telegram.call_configured():
        lang, repeat = str(th("sos", "telegram_call_lang")), int(th("sos", "call_repeat"))
        text = call_text_short(report)
        return in_background(lambda: telegram.place_call(text, lang=lang, repeat=repeat))
    twilio = _module("twilio")
    if twilio is not None and twilio.configured():
        voice, repeat = str(th("sos", "call_voice")), int(th("sos", "call_repeat"))
        return in_background(lambda: twilio.place_sos_call(report, voice=voice, repeat=repeat))
    return "not_connected"


def sms_channel(report: SosReport) -> str | Future[str]:
    """``sms``: the state and the map link (Telegram: plus a map pin and a voice note)."""
    telegram = _module("telegram")
    if telegram is not None and telegram.bot_configured():
        return in_background(lambda: telegram.send_sos_message(report))
    twilio = _module("twilio")
    if twilio is not None and twilio.configured():
        return in_background(lambda: twilio.send_sos_sms(report))
    return "not_connected"


def all_clear(text: str) -> str | Future[str]:
    """The driver answered after the SOS went out: tell the emergency contact (the same way as the message)."""
    telegram = _module("telegram")
    if telegram is not None and telegram.bot_configured():
        return in_background(lambda: telegram.send_message(text))
    twilio = _module("twilio")
    if twilio is not None and twilio.configured():
        return in_background(lambda: twilio.send_sms(text))
    return "not_connected"

