"""The SOS to the emergency contact on Telegram: the bot's message (text, map pin, voice note) and the Telegram call
(CallMeBot). Nothing is ever sent from here: HTTP is faked, and integrations.telegram_alert is not_connected under
pytest by default."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from p2_helpers import Rig

from core.safety import channels
from integrations import telegram_alert
from shared import contracts as c

TOKEN = "123456:SECRET-token"


@pytest.fixture
def fake_telegram(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Telegram configured, with a fake HTTP client that records the requests."""
    for name, value in {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42", "TELEGRAM_CALL_USER": "cristian_x",
                        "DRIVEMATE_TELEGRAM_LIVE": "1"}.items():
        monkeypatch.setenv(name, value)
    sent: dict[str, Any] = {"posts": [], "gets": [], "bot_ok": True, "call_page": "<p>Call queued</p>", "status": 200}

    class Http:
        def __enter__(self) -> Http:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> Any:
            sent["posts"].append({"method": url.rsplit("/", 1)[-1], "url": url, "data": data, "files": files})
            body = {"ok": True, "result": {}} if sent["bot_ok"] else {"ok": False, "error_code": 400,
                                                                       "description": "Bad Request: chat not found"}
            return SimpleNamespace(json=lambda: body)

        def get(self, url: str, params: dict[str, Any]) -> Any:
            sent["gets"].append({"url": url, "params": params})
            return SimpleNamespace(status_code=sent["status"], text=sent["call_page"])

    monkeypatch.setattr(telegram_alert, "_http", Http)
    monkeypatch.setattr(telegram_alert, "voice_mp3", lambda text: b"ID3 fake mp3 " + text.encode())
    return sent


def report() -> c.SosReport:
    return c.SosReport(driver_name="Andrei", unresponsive_s=24.0, cause="Andrei a închis ochii la volan.",
                       pos=c.Position(lat=45.71, lon=21.08), text="Alertă automată DriveMate. https://maps",
                       call_text="Alertă automată DriveMate. Andrei nu răspunde.")


def test_nothing_is_sent_from_tests_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_CALL_USER", "x")
    monkeypatch.delenv("DRIVEMATE_TELEGRAM_LIVE", raising=False)
    assert not telegram_alert.bot_configured() and not telegram_alert.call_configured()
    assert telegram_alert.send_sos_message(report()) == "not_connected"
    assert telegram_alert.place_call("x", lang="ro-RO-Standard-A") == "not_connected"


# --- the message -------------------------------------------------------------------------------------------------------


def test_the_message_has_the_text_the_map_pin_and_the_voice_note(fake_telegram: dict[str, Any]) -> None:
    assert telegram_alert.send_sos_message(report()) == "sent"
    methods = [p["method"] for p in fake_telegram["posts"]]
    assert methods == ["sendMessage", "sendLocation", "sendVoice"]
    text, pin, voice = fake_telegram["posts"]
    assert text["data"] == {"chat_id": "42", "text": "Alertă automată DriveMate. https://maps"}
    assert (pin["data"]["latitude"], pin["data"]["longitude"]) == (45.71, 21.08)
    name, audio, mime = voice["files"]["voice"]
    assert mime == "audio/mpeg" and b"Andrei nu r" in audio  # the call text, read aloud


def test_a_refused_message_is_an_error_without_the_token(fake_telegram: dict[str, Any]) -> None:
    fake_telegram["bot_ok"] = False
    status = telegram_alert.send_sos_message(report())
    assert status.startswith("error: RuntimeError: sendMessage: 400 Bad Request: chat not found")
    assert len(fake_telegram["posts"]) == 1  # no pin, no voice note after a refused text
    assert TOKEN not in telegram_alert._clean(RuntimeError(f"https://api.telegram.org/bot{TOKEN}/sendMessage"))


# --- the call ----------------------------------------------------------------------------------------------------------


def test_the_call_reads_a_short_state_in_romanian(fake_telegram: dict[str, Any]) -> None:
    assert telegram_alert.place_call("Alertă DriveMate. " * 30, lang="ro-RO-Standard-A", repeat=2) == "started"
    params = fake_telegram["gets"][0]["params"]
    assert params["user"] == "@cristian_x" and params["lang"] == "ro-RO-Standard-A" and params["rpt"] == 2
    assert params["cc"] == "no" and len(params["text"]) <= 256


def test_a_call_callmebot_refuses_is_an_error(fake_telegram: dict[str, Any]) -> None:
    fake_telegram["call_page"] = "<b>Error:</b> user @cristian_x not authorized"
    assert telegram_alert.place_call("x", lang="ro-RO-Standard-A").startswith("error: 200 Error: user")


def test_a_busy_callmebot_is_asked_again(fake_telegram: dict[str, Any]) -> None:
    flood = ("Autorization OK Starting Telegram Audio Call. Error: FLOOD - Too many users making calls at this time. "
             "This call was skipped.")
    too_soon = "ERROR: Two calls to the same user (@cristian_x) within 65 seconds is not allowed."
    pages = [flood, too_soon, "Autorization OK Starting Telegram Audio Call. Script ended. End."]
    real_get = telegram_alert._http.get

    def get(self: Any, url: str, params: dict[str, Any]) -> Any:
        real_get(self, url, params)
        return SimpleNamespace(status_code=200, text=pages.pop(0))

    telegram_alert._http.get = get  # type: ignore[method-assign]
    assert telegram_alert.place_call("x", lang="ro-RO-Standard-A", retry_s=0.0) == "started"
    assert len(fake_telegram["gets"]) == 3
    pages[:] = [flood] * 4
    status = telegram_alert.place_call("x", lang="ro-RO-Standard-A", attempts=2, retry_s=0.0)
    assert status.startswith("error: 200 Error: FLOOD") and len(fake_telegram["gets"]) == 5


def test_the_short_call_text_from_the_report() -> None:
    text = channels.call_text_short(report())
    assert text == ("Alertă DriveMate. Andrei nu răspunde de 24 secunde. Andrei a închis ochii la volan. "
                    "Locația e în mesajul trimis pe Telegram.")
    assert telegram_alert.short_text("a " * 200).endswith(".") and len(telegram_alert.short_text("a " * 200)) <= 256


# --- core picks Telegram first, Twilio otherwise -------------------------------------------------------------------------


def test_core_uses_telegram_before_twilio(fake_telegram: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integrations.twilio_call.configured", lambda: True)
    monkeypatch.setattr("integrations.twilio_call.place_sos_call", lambda *a, **k: pytest.fail("Twilio was called"))
    rig = Rig(scene=8)  # the real channels
    rig.run(1.0)
    rig.press("8")
    rig.run_until(lambda: rig.engine.safety.sos.state == "sos_sent", limit_s=60.0)
    rig.run_until(lambda: len(rig.hub.events("sos_channel_result")) >= 2, limit_s=5.0)
    results = {e["data"]["sos_channel"]: e["data"]["status"] for e in rig.hub.events("sos_channel_result")}
    assert results == {"call": "started", "sms": "sent"}
    said = [s["text"] for s in rig.speaks()]
    assert "Andrei nu răspunde. Sun contactul de urgență, Cristian." in said
    assert not [t for t in said if "Nu am putut suna" in t]
    call = fake_telegram["gets"][0]["params"]["text"]
    assert call.startswith("Alertă DriveMate. Andrei nu răspunde de ") and "Telegram" in call


def test_without_telegram_core_falls_back_to_twilio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integrations.telegram_alert.call_configured", lambda: False)
    monkeypatch.setattr("integrations.telegram_alert.bot_configured", lambda: False)
    monkeypatch.setattr("integrations.twilio_call.configured", lambda: True)
    monkeypatch.setattr("integrations.twilio_call.place_sos_call", lambda report, **k: "answered")
    monkeypatch.setattr("integrations.twilio_call.send_sos_sms", lambda report: "sent")
    assert channels.call_channel(report()).result(timeout=2) == "answered"
    assert channels.sms_channel(report()).result(timeout=2) == "sent"


def test_nothing_set_up_is_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_CALL_USER", "DRIVEMATE_TELEGRAM_LIVE",
                 "DRIVEMATE_TWILIO_LIVE"):
        monkeypatch.delenv(name, raising=False)
    assert channels.call_channel(report()) == "not_connected"
    assert channels.sms_channel(report()) == "not_connected"
    assert channels.all_clear("x") == "not_connected"
