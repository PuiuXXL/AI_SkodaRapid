"""K: route reminders. The rule decides, the LLM only understands the request (K1, P3) and phrases the stop (K3).

* **K2** (:class:`ReminderRule`): the car stopped (``speed <= reminders.stopped_max_kmh`` for ``stopped_min_s``) at a
  POI of a reminder's category -> the fixed text "Ai zis să iei lichid de parbriz." (several tasks joined with " și ")
  and a dialog window. Yes (voice, nod, thumbs up) = done ("Gata."); no (voice, shake, thumbs down) = kept for the
  next stop; no answer = kept. Once per stop; only with the car stopped (zero distraction). Not a P3-P4 initiative
  but the driver's own request, so it is said even while the assistant is silenced after a refusal (scene 7 follows
  scene 6); never during a safety alert.
* **K3** (:func:`pick_stop`): after a high KSS answer, the stop is the next POI ahead within
  ``reminders.stop_search_km``; an open reminder of the same category is solved there too ("Oprim la OMV peste
  12 km? Iei și lichidul de parbriz.").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core import clips
from core.attractions import attraction_stop, attractions_ahead
from core.safety.answers import Answer, parse_gesture, parse_voice
from core.settings import render, template, th
from shared.contracts import LLM_VETO_LEVELS, PerceptionFrame, State, UiSpeech

if TYPE_CHECKING:
    from core.engine import Engine


def pick_stop(state: State) -> dict[str, Any] | None:
    """The ``stop_suggested`` event data for a break, or None when there is no stop ahead in range.

    A tourist sight on the map route (K4, ``core/attractions.py``) wins over the next stop, unless an open reminder
    needs that stop: a break at Salina Turda rather than at a fuel station, but the windscreen fluid first.
    """
    sights = [s for s in attractions_ahead(state) if float(s["dist_km"]) <= float(th("reminders", "stop_search_km"))]
    poi = state.trip.next_poi
    needed = poi is not None and any(r.state == "active" and r.trigger.category == poi.category
                                     for r in state.reminders)
    if sights and not needed:
        return attraction_stop(sights[0])
    if poi is None or (poi.dist_km is not None and poi.dist_km > float(th("reminders", "stop_search_km"))):
        return None
    task = next((r.task for r in state.reminders
                 if r.state == "active" and r.trigger.category == poi.category), None)
    data: dict[str, Any] = {"poi_id": poi.id, "poi_name": poi.name or poi.id, "dist_km": poi.dist_km,
                            "poi_options": [poi.id]}
    if task:
        data["task"] = task
    return data


class ReminderRule:
    """K2. Registered before the assistant link: an answer to "Ai zis să iei ..." never reaches the LLM."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        engine.reminders = self
        engine.add_tick_listener(self.on_tick)
        engine.add_browser_listener(self.on_browser)
        engine.add_frame_listener(self.on_frame)
        engine.add_reset_listener(self.reset)
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.stopped_since: float | None = None
        self.handled_stop: str | None = None
        self.pending: list[str] = []  # reminder ids waiting for the answer
        self.pending_until = 0.0
        self.last_inputs: tuple[Any, Any] = (None, None)

    # --- the stop ------------------------------------------------------------------------------------------------

    def on_tick(self, state: State, now: float) -> None:
        if self.pending and now > self.pending_until:
            self._kept(now, answered=False)
        trip = state.trip
        if trip.at_poi is None or trip.speed_kmh > float(th("reminders", "stopped_max_kmh")):
            self.stopped_since, self.handled_stop = None, None
            return
        self.stopped_since = now if self.stopped_since is None else self.stopped_since
        poi = trip.at_poi
        if self.handled_stop == poi.id or now - self.stopped_since < float(th("reminders", "stopped_min_s")):
            return
        if (state.safety.level or "P4") in LLM_VETO_LEVELS:
            return  # after the alert, not over it
        self.handled_stop = poi.id
        due = [r for r in state.reminders if r.state == "active" and r.trigger.type == "stop_at_category"
               and r.trigger.category == poi.category]
        if not due:
            return
        text = render("reminders", "due", task=" și ".join(r.task for r in due))
        self.engine.say(None, text, is_question=True, expects="yes_no", prefix="rem")
        window = float(th("dialog", "window_s")) + 2.0  # the sentence itself takes ~2 s
        self.engine.safety.dialog.open(now, window, "driver", reason="reminder")
        self.pending, self.pending_until = [r.id for r in due], now + window
        self.engine.log_event("reminder_due", now, text=text, reminder_ids=self.pending, poi_id=poi.id,
                              poi=poi.name or poi.id)

    # --- the answer ----------------------------------------------------------------------------------------------

    def on_browser(self, message: Any, now: float) -> None:
        if not self.pending or not isinstance(message, UiSpeech) or not message.final:
            return
        if self.engine.safety.sos.state != "normal":
            return
        answer = parse_voice(message.text)
        if answer is not None:
            self._resolve(answer, "voice", now)

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        current = (frame.driver.head.answer, frame.driver.gesture)
        new = [value for value, before in zip(current, self.last_inputs, strict=True) if value and value != before]
        self.last_inputs = current
        if not self.pending or not new or self.engine.safety.sos.state != "normal":
            return
        if current[0] in new and current[0] in ("yes", "no"):
            self._resolve(current[0], "nod" if current[0] == "yes" else "shake", now)  # type: ignore[arg-type]
        elif (gesture := parse_gesture(current[1])) is not None:
            self._resolve(gesture, "gesture", now)

    def _resolve(self, answer: Answer, channel: str, now: float) -> None:
        self.engine.input_consumed_at = now
        if answer == "no":
            self._kept(now, answered=True, channel=channel)
            return
        state = self.engine.state
        done = [r for r in state.reminders if r.id in self.pending and r.state != "done"]
        for reminder in done:
            reminder.state = "done"
        state.scorecard.reminders_done += len(done)
        clip_id = str(template("clips", "confirm_done"))
        self.engine.say(clip_id, clips.clip_text(clip_id, "Gata."), prefix="rem")
        self.engine.safety.dialog.close(now)
        tasks = ", ".join(r.task for r in done)
        self.engine.log_event("reminder_done", now, channel=channel, text=f"Memento bifat: {tasks}.",
                              reminder_ids=[r.id for r in done])
        self.pending = []

    def _kept(self, now: float, *, answered: bool, channel: str | None = None) -> None:
        if answered:
            self.engine.say(None, str(template("reminders", "kept")), prefix="rem")
            self.engine.safety.dialog.close(now)
        self.engine.log_event("reminder_kept", now, channel=channel, reminder_ids=self.pending,
                              text="Mementoul rămâne pentru următoarea oprire.")
        self.pending = []
