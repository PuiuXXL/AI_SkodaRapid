"""After the SOS was sent the driver can still say / show that they are fine, and everything works again (live test
2026-11-22: once in the SOS nothing reset and nothing worked any more)."""

from __future__ import annotations

import pytest
from p2_helpers import FakeClient, Rig

from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio


def sos_sent_rig(client: FakeClient | None = None) -> Rig:
    rig = Rig(scene=8, assistant=client)
    rig.run(1.0)
    rig.press("8")  # the head falls, the eyes stay shut, no answer
    rig.run_until(lambda: rig.engine.safety.sos.state == "sos_sent", limit_s=60.0)
    rig.press("1")  # the driver comes round: eyes open, face seen
    rig.run(0.5)
    return rig


def back_to_normal(rig: Rig) -> None:
    sos = rig.engine.safety.sos
    assert sos.state == "normal" and rig.state.safety.level is None and rig.state.safety.llm_allowed is True
    assert rig.hub.events("sos_cancelled")[-1]["data"]["stage"] == "sos_sent"


async def test_the_window_stays_open_after_the_sos_is_sent() -> None:
    rig = sos_sent_rig()
    assert rig.state.interaction.dialog_window_open is True
    windows = [m for m in rig.hub.perception_sent if m.get("cmd") == "dialog_window"]
    assert windows[-1]["open"] is True  # P1 keeps looking for a nod / a thumbs up
    rig.run(th("sos", "sent_window_s") * 2)
    assert rig.state.interaction.dialog_window_open is True  # refreshed, never closed while the SOS lasts


async def test_sunt_bine_without_the_wake_word_ends_it() -> None:
    rig = sos_sent_rig()
    rig.say("Sunt bine.", addressed=False)  # the browser may not mark it addressed: core's window is enough
    rig.run(0.2)
    back_to_normal(rig)
    assert rig.state.interaction.dialog_window_open is False


@pytest.mark.parametrize("key", ["g", "y"])
async def test_a_thumbs_up_or_a_nod_ends_it(key: str) -> None:
    rig = sos_sent_rig()
    rig.press(key)
    rig.run(0.3)
    back_to_normal(rig)


async def test_the_driver_is_told_how_to_cancel() -> None:
    rig = sos_sent_rig()
    rig.run(th("sos", "sent_reask_s") + 0.5)
    asks = [s["text"] for s in rig.speaks() if s["text"].startswith("Andrei, am chemat ajutor.")]
    assert asks and rig.hub.events("sos_sent_ask")


async def test_after_it_the_assistant_answers_again() -> None:
    client = FakeClient({"driver_speech": [c.Action(type="speak", to="driver", text="Mai ai 20 de minute.")]})
    rig = sos_sent_rig(client)
    rig.say("Sunt bine.", addressed=False)
    rig.run(1.0)
    back_to_normal(rig)
    rig.say("copilot, cât mai am?")
    await rig.link.drain()
    assert "Mai ai 20 de minute." in [s["text"] for s in rig.speaks()]
