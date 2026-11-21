"""Tests for answer fusion (E3), TTS message building (D4), the router and the phone bridge filters."""

import asyncio

import pytest

from assistant.answers import InputEvent, fuse, interpret_voice
from assistant.contract import Action
from assistant.textutil import split_sentences
from assistant.tts import SpeechCache, speak_message

# ----------------------------------------------------------------- answers (plan E3)


def test_voice_yes_no():
    assert interpret_voice("Da, te rog") == "yes"
    assert interpret_voice("sigur") == "yes"
    assert interpret_voice("Nu, mulțumesc") == "no"
    assert interpret_voice("cât e ceasul") is None


def test_refusal_only_in_fatigue_dialog():
    assert interpret_voice("Lasă-mă în pace", fatigue_dialog=True) == "refusal"
    assert interpret_voice("Lasă-mă în pace", fatigue_dialog=False) is None


def test_fuse_takes_the_earliest_answer_with_its_channel():
    answer = fuse([
        InputEvent("voice", "da", ts=10.4),
        InputEvent("nod", "yes", ts=10.1),
        InputEvent("gesture", "Thumb_Down", ts=10.6),
    ])
    assert (answer.value, answer.channel, answer.ts) == ("yes", "nod", 10.1)


def test_palm_and_thumb_down_are_refusals_in_fatigue_dialog():
    assert fuse([InputEvent("gesture", "Open_Palm", 1.0)]).value == "silence"
    assert fuse([InputEvent("gesture", "Open_Palm", 1.0)], fatigue_dialog=True).value == "refusal"
    assert fuse([InputEvent("gesture", "Thumb_Down", 1.0)], fatigue_dialog=True).value == "refusal"


def test_nothing_recognisable():
    assert fuse([InputEvent("voice", "hmm", 1.0), InputEvent("gesture", "None", 2.0)]) is None


# ----------------------------------------------------------------- TTS (plan D4)


def test_split_sentences():
    assert split_sentences("Salut Andrei. Merge bine? Da!") == ["Salut Andrei.", "Merge bine?", "Da!"]


def test_speak_message_has_one_url_per_sentence():
    message = speak_message(Action(type="ask", to="driver", question="Pare monoton. Pun ceva?", expects="yes_no"), "u1")
    assert message["is_question"] is True and message["id"] == "u1"
    assert [s["text"] for s in message["sentences"]] == ["Pare monoton.", "Pun ceva?"]
    assert all(s["url"] == f"/tts/{s['id']}.mp3" for s in message["sentences"])


def test_speak_message_uses_clip_instead_of_tts():
    message = speak_message(Action(type="speak", to="driver", text="Ok, te las în pace.", clip_id="refusal_ack"))
    assert message["clip_url"] == "/sounds/clips/refusal_ack.mp3" and message["sentences"] == []


def test_speech_cache_streams_one_synthesis_to_all_readers(monkeypatch):
    calls = []

    async def fake_chunks(text, voice=None, rate=None):
        calls.append(text)
        for part in (b"mp", b"3"):
            await asyncio.sleep(0.01)
            yield part

    monkeypatch.setattr("assistant.tts.audio_chunks", fake_chunks)
    cache = SpeechCache(size=2)
    speech_id = cache.register("Salut.")

    async def scenario():
        cache.prefetch(speech_id)                       # started by speak_message
        both = await asyncio.gather(cache.get(speech_id), cache.get(speech_id))
        streamed = [chunk async for chunk in cache.stream(speech_id)]   # now from the LRU cache
        return both, streamed

    both, streamed = asyncio.run(scenario())
    assert both == [b"mp3", b"mp3"] and streamed == [b"mp3"]
    assert calls == ["Salut."]                          # one edge-tts call for everyone
    with pytest.raises(KeyError):
        asyncio.run(cache.get("unknown"))


def test_speech_cache_reports_failure(monkeypatch):
    async def broken(text, voice=None, rate=None):
        raise OSError("no internet")
        yield b""  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("assistant.tts.audio_chunks", broken)
    cache = SpeechCache()
    speech_id = cache.register("Salut.")
    with pytest.raises(RuntimeError):
        asyncio.run(cache.get(speech_id))


# ----------------------------------------------------------------- router


def test_router_404s():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from assistant.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/tts/does-not-exist.mp3").status_code == 404
    assert client.get("/media/t99.mp3").status_code == 404
    assert client.get("/assistant/health").json()["language"] == "ro"


# ----------------------------------------------------------------- phone bridge (plan F1, F8)


def test_bridge_whitelist():
    from integrations.phone_bridge import classify

    assert classify("WhatsApp", "Mihai", "Unde ești?") == "whatsapp"
    assert classify("Messages", "Mihai", "Unde ești?") == "sms"
    assert classify("Instagram", "Mihai", "like") is None
    assert classify("WhatsApp", "WhatsApp", "3 mesaje noi") is None  # summary notification
    assert classify("WhatsApp", "Mihai", "") is None


def test_bridge_sms_uses_roles_not_numbers(monkeypatch, capsys):
    from integrations.phone_bridge import PhoneBridge

    bridge = PhoneBridge("dev", dry_run=True)
    monkeypatch.setenv("SAFE_CONTACT_NUMBER", "+40700000000")
    asyncio.run(bridge.send_sms("safe_contact", "DriveMate: test"))
    out = capsys.readouterr().out
    assert "safe_contact" in out and "+40700000000" not in out  # the number is never printed
    with pytest.raises(ValueError):
        asyncio.run(bridge.send_sms("+40711111111", "x"))  # raw numbers are refused
