"""The SOS call to the emergency contact (Twilio): what is said, in the call and in the car. No real call is ever made
here: the Twilio client is faked, and integrations.twilio_call is not_connected under pytest by default."""

from __future__ import annotations

import time
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import pytest
from p2_helpers import Rig

from core import clips
from core.safety.channels import in_background
from integrations import twilio_call
from shared import contracts as c


def done(status: str) -> Future[str]:
    future: Future[str] = Future()
    future.set_result(status)
    return future


def sos_sent(channels: dict[str, Any]) -> Rig:
    rig = Rig(scene=8, sos_channels=channels)
    rig.run(1.0)
    rig.press("8")  # the head falls, the eyes stay shut, no answer
    rig.run_until(lambda: rig.engine.safety.sos.state == "sos_sent", limit_s=60.0)
    rig.run(0.3)
    return rig


def said(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


# --- what the contact hears ---------------------------------------------------------------------------------------------


def test_the_call_says_the_state_and_the_cause_without_a_link() -> None:
    reports: list[c.SosReport] = []
    rig = sos_sent({"call": lambda report: reports.append(report) or "ok"})
    report = reports[0]
    assert report.cause == "Lui Andrei i-a căzut capul la volan, mergând cu 118 la oră."
    assert report.call_text.startswith("Alertă automată DriveMate. Andrei nu răspunde de ")
    assert report.cause in report.call_text and "Locația a fost trimisă prin SMS." in report.call_text
    assert "http" not in report.call_text  # a link cannot be read aloud
    assert report.cause in report.text and "https://" in report.text  # the SMS has the map
    assert rig.engine.safety.sos.state == "sos_sent"


def test_the_twiml_reads_it_twice_and_is_escaped() -> None:
    xml = twilio_call.build_twiml("A & B <ok>", voice="Polly.Carmen", repeat=2)
    assert xml.count("<Say ") == 2 and '<Pause length="1"/>' in xml
    assert "A &amp; B &lt;ok&gt;" in xml and 'language="ro-RO"' in xml and 'voice="Polly.Carmen"' in xml


# --- what the car hears -----------------------------------------------------------------------------------------------


def test_the_car_hears_who_is_called_and_the_outcome() -> None:
    assert clips.emergency_contact_name(Rig(scene=8).state) == "Cristian"  # assistant.yaml
    rig = sos_sent({"call": lambda report: done("answered"), "sms": lambda report: done("sent")})
    assert "Andrei nu răspunde. Sun contactul de urgență, Cristian." in said(rig)
    assert "Cristian a răspuns la apel și știe unde suntem." in said(rig)
    results = {e["data"]["sos_channel"]: e["data"]["status"] for e in rig.hub.events("sos_channel_result")}
    assert results == {"call": "answered", "sms": "sent"}
    assert rig.hub.events("sos_sent")[0]["data"]["channels"] == {"call": "started", "sms": "started"}


@pytest.mark.parametrize(("status", "sentence"), [
    ("no_answer", "Cristian nu a răspuns. I-am trimis locația prin SMS."),
    ("busy", "Cristian nu a răspuns. I-am trimis locația prin SMS."),
    ("error: TwilioRestException: unverified", "Nu am putut suna contactul de urgență."),
])
def test_a_call_that_did_not_get_through_is_said(status: str, sentence: str) -> None:
    rig = sos_sent({"call": lambda report: done(status)})
    assert sentence in said(rig)


def test_nothing_is_announced_without_twilio() -> None:
    rig = sos_sent({"call": lambda report: "not_connected"})
    assert not [t for t in said(rig) if "contactul de urgență" in t]


def test_a_slow_call_does_not_block_the_car() -> None:
    def slow() -> str:
        time.sleep(0.5)
        return "answered"

    rig = sos_sent({"call": lambda report: in_background(slow)})
    assert "Cristian a răspuns la apel și știe unde suntem." not in said(rig)  # still ringing
    deadline = time.time() + 3.0
    while "Cristian a răspuns la apel și știe unde suntem." not in said(rig) and time.time() < deadline:
        time.sleep(0.05)
        rig.run(0.1)
    assert "Cristian a răspuns la apel și știe unde suntem." in said(rig)


# --- the driver answers after it: the contact is told -------------------------------------------------------------------


def test_sunt_bine_after_the_sos_tells_the_contact() -> None:
    sms: list[str] = []
    rig = sos_sent({"call": lambda report: done("answered")})
    rig.engine.safety.sos.all_clear = lambda text: sms.append(text) or done("sent")
    rig.press("1")
    rig.say("Sunt bine.", addressed=False)
    rig.run(0.3)
    assert rig.engine.safety.sos.state == "normal"
    assert sms and sms[0].startswith("DriveMate: Andrei a răspuns după alertă și spune că e bine.")
    assert "Îi spun lui Cristian că ești bine." in said(rig)


# --- integrations/twilio_call.py with a fake Twilio client ----------------------------------------------------------------


@pytest.fixture
def fake_twilio(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Twilio configured, with a fake client: records the requests, answers with scripted call statuses."""
    for name, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "token",
                        "TWILIO_FROM_NUMBER": "+10000000000", "EMERGENCY_NUMBER": "+40700000000",
                        "DRIVEMATE_TWILIO_LIVE": "1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TWILIO_VOICE", raising=False)
    sent: dict[str, Any] = {"statuses": ["ringing", "in-progress", "completed"], "calls": [], "sms": []}

    class Calls:
        def create(self, **kwargs: Any) -> Any:
            sent["calls"].append(kwargs)
            return SimpleNamespace(sid="CA1", status="queued")

        def __call__(self, sid: str) -> Any:
            return SimpleNamespace(fetch=lambda: SimpleNamespace(status=sent["statuses"].pop(0)))

    class Messages:
        def create(self, **kwargs: Any) -> Any:
            sent["sms"].append(kwargs)
            return SimpleNamespace(sid="SM1")

    monkeypatch.setattr(twilio_call, "_client", lambda: SimpleNamespace(calls=Calls(), messages=Messages()))
    return sent


def test_twilio_is_never_called_from_tests_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.delenv("DRIVEMATE_TWILIO_LIVE", raising=False)
    assert not twilio_call.configured()
    assert twilio_call.place_sos_call(c.SosReport(), voice="x") == "not_connected"


def test_the_call_request_and_its_outcome(fake_twilio: dict[str, Any]) -> None:
    report = c.SosReport(call_text="Alertă automată DriveMate. Andrei nu răspunde.", text="SMS")
    assert twilio_call.place_sos_call(report, voice="Polly.Carmen", poll_s=0.0) == "answered"
    call = fake_twilio["calls"][0]
    assert (call["to"], call["from_"], call["timeout"]) == ("+40700000000", "+10000000000", 30)
    assert "Andrei nu răspunde." in call["twiml"]
    assert twilio_call.send_sos_sms(report) == "sent" and fake_twilio["sms"][0]["body"] == "SMS"


def test_a_trial_account_is_called_without_the_ring_timeout(fake_twilio: dict[str, Any],
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class TrialCalls:
        def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            if "timeout" in kwargs:
                raise RuntimeError("HTTP 400 error: Invalid or disallowed parameters provided - trial accounts have "
                                   "limited parameter access")
            return SimpleNamespace(sid="CA1", status="completed")

    monkeypatch.setattr(twilio_call, "_client", lambda: SimpleNamespace(calls=TrialCalls()))
    assert twilio_call.place_sos_call(c.SosReport(call_text="x"), voice="v", poll_s=0.0) == "answered"
    assert "timeout" in calls[0] and "timeout" not in calls[1] and calls[1]["twiml"]


def test_a_call_nobody_answers(fake_twilio: dict[str, Any]) -> None:
    fake_twilio["statuses"] = ["ringing", "no-answer"]
    assert twilio_call.place_sos_call(c.SosReport(call_text="x"), voice="v", poll_s=0.0) == "no_answer"


def test_a_refused_call_is_an_error_not_an_exception(fake_twilio: dict[str, Any],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> Any:
        raise RuntimeError("The number is unverified")

    monkeypatch.setattr(twilio_call, "_client", refuse)
    assert twilio_call.place_sos_call(c.SosReport(call_text="x"), voice="v").startswith("error: RuntimeError")
    assert twilio_call.send_sms("x").startswith("error: RuntimeError")
