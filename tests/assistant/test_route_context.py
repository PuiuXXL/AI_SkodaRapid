"""P3 with the map route (P4 simulator): the place and the sights ahead reach the LLM; a sight may be proposed."""

from __future__ import annotations

from assistant import fallback
from assistant.actions import _allowed_poi_ids
from assistant.summary import summarize
from shared import contracts as c


def map_state() -> c.State:
    state = c.State()
    state.trip = c.Trip(speed_kmh=90, road="highway", elapsed_min=20, eta_min=30,
                        next_poi=c.Poi(id="turda", category="destination", name="Turda", dist_km=40.0),
                        place={"after": "Cluj-Napoca", "after_km": 12.3, "before": "Turda", "before_km": 40.1,
                               "destination": "Turda", "destination_km": 40.1},
                        attractions_ahead=[{"id": "wiki-ro-2", "name": "Salina Turda", "kind": "museum", "dist_km": 8.0,
                                            "detour_km": 1.2, "description": "O salină veche."}])
    return state


def test_the_llm_reads_the_place_in_names_and_the_sights_with_their_description() -> None:
    text = summarize(map_state(), c.Event(type="driver_speech", data={"text": "unde suntem?"}))
    assert ("Location: after Cluj-Napoca (12.3 km behind), before Turda (40.1 km ahead); "
            "destination Turda in 40.1 km") in text
    assert 'Salina Turda [wiki-ro-2] (museum, in 8 km, 1.2 km off the road): "O salină veche."' in text
    assert "Location:" not in summarize(c.State(), c.Event(type="trip_start"))  # core's demo trip: nothing new


def test_a_sight_ahead_may_be_suggested_as_a_stop() -> None:
    assert _allowed_poi_ids(map_state(), None) == {"turda", "wiki-ro-2"}


def test_the_fixed_question_for_a_sight() -> None:
    event = c.Event(type="stop_suggested", data={"poi_id": "wiki-ro-2", "poi_name": "Salina Turda", "dist_km": 8.0,
                                                 "kind": "attraction"})
    actions = fallback.build_fallback(event, map_state())
    assert actions[0]["question"] == "Peste 8 km e Salina Turda. Facem o pauză acolo?"
    assert actions[1] == {"type": "suggest_stop", "poi_id": "wiki-ro-2"}
    event.data["dist_km"] = 12.9  # said rounded
    question = fallback.build_fallback(event, map_state())[0]["question"]
    assert question == "Peste 13 km e Salina Turda. Facem o pauză acolo?"


def test_the_llm_reads_the_name_of_the_place_it_stopped_at() -> None:
    state = map_state()
    state.trip.speed_kmh, state.trip.stopped = 0, True
    state.trip.at_poi = c.Poi(id="wiki-ro-2", category="attraction", name="Salina Turda")
    assert "STOPPED at Salina Turda [wiki-ro-2] (attraction)" in summarize(state, c.Event(type="driver_speech"))
