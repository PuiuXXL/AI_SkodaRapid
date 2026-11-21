"""Tests for YouTube music / podcasts on request (assistant/media_search.py, docs/assistant.md 6.1).

The network is never used: ``media_search.search`` is replaced by a fake that returns fixed results.
"""

import pytest

from assistant import media_search, music
from assistant.actions import validate_actions
from assistant.answers import InputEvent
from assistant.client import AssistantClient
from assistant.contract import Action, Event
from assistant.dialog import DialogManager
from assistant.fallback import build_fallback
from assistant.llm import OfflineProvider
from assistant.media_search import MediaResult, MediaSearchError
from assistant.router import parse_range
from assistant.textutil import word_count
from p3_helpers import FakeProvider, make_state

NOW = 1763672400.0

RESULTS = [
    MediaResult("uhBHL3v4d3I", "Metallica: Hardwired (Official Music Video)", "Metallica", 199),
    MediaResult("6fVE8kSM43I", "Slipknot - Duality [OFFICIAL VIDEO] [HD]", "Slipknot", 254),
    MediaResult("vgrwacUZF9A", "Nu Metal Revolution Vol.81 | Inspired Heavy Rock Mix", "Shadow Cathedral", 3000),
    MediaResult("CD-E-LDc384", "Metallica - Enter Sandman (Official Music Video)", "Metallica", 331),
]


def city_state(**overrides):
    """Slow city driving, risk 0: three options are offered."""
    return make_state(trip={"speed_kmh": 40, "road": "city"}, assessment={"risk": 0}, **overrides)


def voice(text, ts=NOW + 1):
    return InputEvent("voice", text, ts)


@pytest.fixture(autouse=True)
def clean_registry():
    media_search.forget_all()
    yield
    media_search.forget_all()


@pytest.fixture
def fake_search(monkeypatch):
    """Replace the network search; records the calls."""
    calls = []

    async def search(query, kind="music", kid_safe=False):
        calls.append((query, kind, kid_safe))
        media_search.remember(RESULTS)
        return list(RESULTS)

    monkeypatch.setattr(media_search, "search", search)
    monkeypatch.setattr(media_search, "prefetch", lambda ids: list(ids))
    return calls


# --- spoken text -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("title, spoken", [
    ("Metallica: Hardwired (Official Music Video)", "Metallica, Hardwired"),
    ("Metallica - Enter Sandman (Official Music Video) [4K Remastered]", "Metallica, Enter Sandman"),
    ("🔥 BEST Of HEAVY METAL 2026 | Legendary Metal Riffs #181", "Best Of Heavy Metal"),
    ("Slipknot - Duality [OFFICIAL VIDEO] [HD]", "Slipknot, Duality"),
    ("Despre istoria Romei | Podcast Istoria Altfel ep. 12", "Despre istoria Romei"),
])
def test_clean_title(title, spoken):
    assert media_search.clean_title(title) == spoken


def test_choice_question_fits_word_limit():
    question, options = media_search.build_choice(RESULTS, 3)
    assert question.startswith("Am găsit:") and question.endswith("Care?")
    assert word_count(question) <= 15
    assert [o["offered"] for o in options] == [True, True, True, False]
    assert options[0]["track_id"] == "yt:uhBHL3v4d3I"


def test_one_option_when_driving_fast():
    assert media_search.offer_size(make_state(trip={"speed_kmh": 118}, assessment={"risk": 0})) == 1
    assert media_search.offer_size(make_state(trip={"speed_kmh": 40}, assessment={"risk": 2})) == 1
    assert media_search.offer_size(city_state()) == 3
    question, _ = media_search.build_choice(RESULTS, 1)
    assert question == "Pun Metallica, Hardwired?"


# --- reading the answer ----------------------------------------------------------------------------------------

BATCH = [o for o in media_search.build_choice(RESULTS, 3)[1] if o["offered"]]


@pytest.mark.parametrize("text, expected", [
    ("a doua", 1), ("prima", 0), ("trei", 2), ("ultima", 2), ("cel cu Slipknot", 1),
    ("altceva", "next"), ("nu", "next"), ("lasă", "cancel"), ("pune ceva jazz", None),
])
def test_parse_choice(text, expected):
    assert media_search.parse_choice(text, BATCH) == expected


def test_yes_picks_the_single_option():
    assert media_search.parse_choice("da", BATCH[:1]) == 0
    assert media_search.parse_choice("da", BATCH) is None  # "yes" to three options is ambiguous


def test_specific_wish_vs_plain_yes():
    assert media_search.is_specific_wish("Da, dă-mi ceva metal energic")
    assert not media_search.is_specific_wish("da, te rog frumos")
    assert not media_search.is_specific_wish("nu")


@pytest.mark.parametrize("text, expected", [
    ("Dă-mi ceva muzică metal energică, te rog", ("muzica metal energica", "music")),
    ("Caută un podcast despre istoria Romei", ("podcast despre istoria romei", "podcast")),
    ("Pune muzică", None),
    ("Cât mai e până ajungem?", None),
])
def test_media_request_without_llm(text, expected):
    assert media_search.media_request(text) == expected


# --- validation ------------------------------------------------------------------------------------------------


def test_search_media_only_at_p4():
    raw = [{"type": "search_media", "query": "energetic metal", "kind": "music"}]
    assert validate_actions(raw, city_state()).accepted
    assert validate_actions(raw, city_state(safety={"level": "P3"})).rejected[0].reason == "not_allowed_at_P3"


def test_play_youtube_only_ids_found_by_a_search():
    play = [{"type": "play_media", "track_id": "yt:uhBHL3v4d3I"}]
    assert validate_actions(play, city_state()).rejected[0].reason == "youtube_track_not_found_by_search"
    media_search.remember(RESULTS)
    assert validate_actions(play, city_state()).accepted


def test_play_youtube_with_child_needs_safe_search():
    media_search.remember(RESULTS)
    child = city_state(occupants=[{"id": 1, "seat": "driver", "profile": "andrei"},
                                  {"id": 3, "seat": "rear", "source": "declared", "profile": "ioana", "role": "child"}])
    play = [{"type": "play_media", "track_id": "yt:uhBHL3v4d3I"}]
    assert validate_actions(play, child).rejected[0].reason == "track_not_kid_safe"


def test_choice_question_needs_options():
    raw = [{"type": "ask", "to": "driver", "question": "Care?", "expects": "choice"}]
    assert validate_actions(raw, city_state()).rejected[0].reason == "choice_without_options"


def test_track_url_and_loop():
    assert music.track_url("yt:uhBHL3v4d3I") == "/media/yt/uhBHL3v4d3I.m4a"
    assert music.track_url("pop1") == "/media/pop1.mp3"
    assert not music.loops("yt:uhBHL3v4d3I") and music.loops("pop1")


# --- client: search_media becomes a spoken choice --------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_search_becomes_choice_question(fake_search):
    answer = {"actions": [{"type": "search_media", "query": "energetic metal", "kind": "music"}]}
    client = AssistantClient(FakeProvider(answer))
    early = []
    event = Event(type="driver_speech", data={"text": "dă-mi ceva metal energic"})
    actions = await client.handle_event(event, city_state(), on_early_speech=early.append, now=NOW)
    assert fake_search == [("energetic metal", "music", False)]
    assert [a.text for a in early] == ["Caut."]
    assert [a.type for a in actions] == ["speak", "ask"] and actions[0].streamed
    ask = actions[1]
    assert ask.expects == "choice" and ask.source == "LLM" and len(ask.options) == 4
    assert "Metallica, Hardwired" in ask.question
    assert client.last_result.reason == "ok"


@pytest.mark.asyncio
async def test_search_works_without_llm(fake_search):
    client = AssistantClient(OfflineProvider())
    event = Event(type="driver_speech", data={"text": "caută un podcast despre istoria Romei"})
    actions = await client.handle_event(event, city_state(), now=NOW)
    assert fake_search[0][:2] == ("podcast despre istoria romei", "podcast")
    assert actions[-1].expects == "choice" and actions[-1].source == "RULE"


@pytest.mark.asyncio
async def test_search_failure_offers_catalog(monkeypatch):
    async def broken(query, kind="music", kid_safe=False):
        raise MediaSearchError("timeout")

    monkeypatch.setattr(media_search, "search", broken)
    monkeypatch.setattr(music, "pick_track", lambda state, reason="disengagement": music.Track(
        id="pop1", title="Pop", artist="", genre="pop", energy=4, kid_safe=False, file="pop1.mp3"))
    monkeypatch.setattr(music, "candidates", lambda state, reason="disengagement": [music.pick_track(state)])
    answer = {"actions": [{"type": "search_media", "query": "jazz", "kind": "music"}]}
    client = AssistantClient(FakeProvider(answer))
    actions = await client.handle_event(Event(type="driver_speech", data={"text": "pune jazz"}), city_state(), now=NOW)
    assert [a.type for a in actions] == ["ask", "suggest_media"]
    assert actions[0].question == "Nu pot căuta acum. Pun ceva din ce am?"
    assert actions[1].needs_confirmation and "timeout" in client.last_result.error


# --- dialog: choosing, "altceva", music offer with a wish ------------------------------------------------------


def _registered(size=3):
    question, options = media_search.build_choice(RESULTS, size)
    media_search.remember(RESULTS)
    dialog = DialogManager()
    ask = Action(type="ask", to="driver", question=question, expects="choice", options=options, reason="media_choice")
    assert dialog.register([ask], NOW) == [ask]
    return dialog


def test_choice_by_ordinal_plays_track():
    dialog = _registered()
    result = dialog.handle([voice("a doua")], NOW + 2, state=city_state())
    assert result.handled and result.answer == "choice"
    play = result.execute[0]
    assert (play.type, play.track_id, play.title) == ("play_media", "yt:6fVE8kSM43I", "Slipknot, Duality")
    assert result.speak[0].text == "Pornesc Slipknot, Duality."
    assert validate_actions([play], city_state()).accepted
    assert not dialog.has_pending(NOW + 3)


def test_altceva_offers_the_remaining_results():
    dialog = _registered()
    result = dialog.handle([voice("altceva")], NOW + 2, state=city_state())
    assert result.speak[0].question == "Pun Metallica, Enter Sandman?"
    assert dialog.handle([InputEvent("gesture", "Thumb_Up", NOW + 4)], NOW + 4).execute[0].track_id == "yt:CD-E-LDc384"


def test_no_more_results_and_cancel():
    dialog = _registered(size=3)
    dialog.handle([voice("altceva")], NOW + 2)
    result = dialog.handle([voice("niciuna")], NOW + 3)
    assert result.speak[0].text == "Altceva n-am găsit. Spune-mi ce să caut."
    dialog = _registered()
    assert dialog.handle([InputEvent("gesture", "Open_Palm", NOW + 2)], NOW + 2).answer == "silence"


def test_new_request_during_choice_is_not_an_answer():
    dialog = _registered()
    assert not dialog.handle([voice("pune ceva jazz")], NOW + 2).handled
    assert dialog.has_pending(NOW + 2)


def test_music_offer_answered_with_a_wish_becomes_a_search_request():
    raw = [{"type": "ask", "to": "driver", "question": "Pare monoton. Pun ceva mai energic?", "expects": "yes_no"},
           {"type": "suggest_media", "track_id": "pop1", "reason": "disengagement"}]
    held = [Action(type=a["type"], **{k: v for k, v in a.items() if k != "type"}) for a in raw]
    held[1] = held[1].model_copy(update={"needs_confirmation": True})
    dialog = DialogManager()
    dialog.register(held, NOW)
    result = dialog.handle([voice("da, dă-mi ceva metal energic")], NOW + 2)
    assert result.handled and [a.type for a in result.cancelled] == ["suggest_media"]
    assert result.events[0].type == "driver_speech" and "metal" in result.events[0].data["text"]
    dialog.register(held, NOW)
    assert dialog.handle([voice("da, te rog")], NOW + 2).execute[0].type == "play_media"  # plain yes: catalog


def test_fallback_without_llm_for_other_speech():
    actions = build_fallback(Event(type="driver_speech", data={"text": "cât e ceasul"}), city_state())
    assert actions[0]["type"] == "speak"


# --- stopping the music ----------------------------------------------------------------------------------------

PLAYING = {"playing": True, "track_id": "yt:uhBHL3v4d3I", "title": "Metallica, Hardwired"}


@pytest.mark.parametrize("text, playing, expected", [
    ("Oprește ce dă play acum", True, True),
    ("oprește muzica", False, True),
    ("stop", True, True),
    ("pune pauză", True, True),
    ("stop", False, False),               # nothing plays: not a media command
    ("oprește aici", True, False),        # stopping the car
    ("oprește la OMV", True, False),
    ("pune ceva rock", True, False),
])
def test_stop_media_request(text, playing, expected):
    from assistant.fallback import stop_media_request

    state = city_state(media=PLAYING if playing else {"playing": False})
    assert stop_media_request(text, state) is expected


@pytest.mark.asyncio
async def test_stop_is_deterministic_and_never_asks_the_llm():
    provider = FakeProvider({"actions": [{"type": "speak", "to": "driver", "text": "Nu ar trebui."}]})
    client = AssistantClient(provider)
    event = Event(type="driver_speech", data={"text": "oprește ce dă play acum"})
    actions = await client.handle_event(event, city_state(media=PLAYING), now=NOW)
    assert [(a.type, a.clip_id) for a in actions] == [("stop_media", None), ("speak", "confirm_ok")]
    assert client.last_result.reason == "deterministic" and provider.calls == []


@pytest.mark.asyncio
async def test_llm_action_without_sentence_gets_ok_instead_of_not_understood():
    client = AssistantClient(FakeProvider({"actions": [{"type": "stop_media"}]}))
    event = Event(type="driver_speech", data={"text": "las-o mai încet, de fapt închide tot"})
    actions = await client.handle_event(event, city_state(media=PLAYING), now=NOW)
    assert [a.type for a in actions] == ["stop_media", "speak"] and actions[1].clip_id == "confirm_ok"
    assert client.last_result.reason == "ok"


# --- volume ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, playing, expected", [
    ("mai încet", True, 0.4),             # 0.6 - step 0.2
    ("dă-l mai tare", True, 0.8),
    ("e prea tare", True, 0.4),           # "prea tare" = quieter
    ("foarte încet", True, 0.2),          # "foarte" doubles the step
    ("pune volumul la jumătate", False, 0.5),
    ("volumul la 30", False, 0.3),
    ("dă muzica la maxim", True, 1.0),
    ("mai încet", False, None),           # nothing plays and no volume word
    ("vorbește mai încet", True, None),   # speech, not the volume
    ("mergi mai încet", True, None),      # speed
    ("pune ceva mai tare", True, None),   # another track -> search
])
def test_volume_request(text, playing, expected):
    from assistant.fallback import volume_request

    media = {**PLAYING, "volume": 0.6} if playing else {"playing": False, "volume": 0.6}
    assert volume_request(text, city_state(media=media)) == expected


def test_volume_stays_within_limits():
    from assistant.fallback import volume_request

    assert volume_request("mai încet", city_state(media={**PLAYING, "volume": 0.1})) == 0.05
    assert volume_request("mai tare", city_state(media={**PLAYING, "volume": 0.95})) == 1.0


@pytest.mark.asyncio
async def test_volume_is_deterministic_and_needs_no_confirmation():
    provider = FakeProvider({"actions": []})
    client = AssistantClient(provider)
    event = Event(type="driver_speech", data={"text": "mai încet"})
    actions = await client.handle_event(event, city_state(media={**PLAYING, "volume": 0.6}), now=NOW)
    volume = actions[0]
    assert (volume.type, volume.key, float(volume.value), volume.needs_confirmation) == ("set_preference", "volume",
                                                                                         0.4, False)
    assert actions[1].clip_id == "confirm_ok" and provider.calls == []
    assert DialogManager().register(actions, NOW) == actions   # nothing held for a "yes"


def test_other_preferences_still_need_confirmation():
    raw = [{"type": "set_preference", "key": "talkativeness", "value": "low"}]
    assert validate_actions(raw, city_state()).accepted[0].needs_confirmation


# --- router helpers --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("header, expected", [
    ("bytes=0-", (0, None, True)), ("bytes=100-199", (100, 199, True)), (None, (0, None, False)),
    ("bytes=-500", (0, None, False)),
])
def test_parse_range(header, expected):
    assert parse_range(header) == expected
