"""B3 attention and risk, B6 blind meters, B9 conversation in the car.

* **attention** 0..1: share of the last ``attention.window_s`` with the gaze on the road and the eyes open (P1's
  ``off_road_ms`` is 0 on the road and during short mirror glances; eyes closed for ``attention.eyes_closed_ms`` or
  more count as off the road, whatever the zone; other ``unknown`` samples are skipped), minus ``vats_penalty`` per
  VATS glance above ``vats_free``, minus ``phone_penalty`` with the phone in hand. Held while the camera is lost.
* **risk** 0..3: ``(w_inattention·(1 - attention) + w_fatigue·F) x min(1, speed / speed_ref_kmh)``, then
  ``risk.levels``: 0 when parked, maximum at 130 km/h.
* **blind meters**: speed x time while ``off_road_ms > 0``: ``last`` = the current (or last) glance, ``trip`` = total.
* **conversation**: the lips of the two cameras alternate (``min_turns`` speaker changes driver <-> passenger in
  ``window_s``) and the microphone heard voice in the last ``mic_recent_s`` (``speech_onset`` / ``speech`` from the
  browser; without any browser voice in this trip the lips alone decide). Held ``hold_s`` after the last turn.
"""

from __future__ import annotations

from collections import deque

from core.settings import th
from shared.contracts import State


class AttentionScore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.value = 1.0
        self.samples: deque[tuple[float, bool]] = deque()

    def update(self, state: State, now: float) -> float:
        gaze, eyes = state.driver.gaze, state.driver.eyes
        # a closure longer than a blink: not watching the road, even with the head straight (the zone stays "road")
        closed = eyes.long_closure or eyes.closed_ms >= float(th("attention", "eyes_closed_ms"))
        if state.safety.monitoring_ok and (closed or gaze.zone != "unknown"):
            self.samples.append((now, not closed and gaze.off_road_ms <= 0))
        while self.samples and self.samples[0][0] < now - float(th("attention", "window_s")):
            self.samples.popleft()
        if not self.samples or not state.safety.monitoring_ok:
            return self.value
        share = sum(1 for _, on_road in self.samples if on_road) / len(self.samples)
        vats = max(0, gaze.vats_60s - int(th("attention", "vats_free"))) * float(th("attention", "vats_penalty"))
        phone = float(th("attention", "phone_penalty")) if state.driver.phone.in_use else 0.0
        self.value = min(1.0, max(0.0, share - vats - phone))
        return self.value


def risk_level(attention: float, fatigue: float, speed_kmh: float) -> int:
    factor = min(1.0, max(0.0, speed_kmh) / float(th("risk", "speed_ref_kmh")))
    weights = th("risk", "weights")
    raw = (float(weights["inattention"]) * (1.0 - attention) + float(weights["fatigue"]) * fatigue) * factor
    return sum(1 for level in th("risk", "levels") if raw >= float(level))


class BlindMeters:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last = self.trip = 0.0
        self.in_glance = False
        self.last_t: float | None = None

    def update(self, state: State, now: float) -> None:
        dt = 0.0 if self.last_t is None else now - self.last_t
        self.last_t = now
        off_road = state.safety.monitoring_ok and state.driver.gaze.off_road_ms > 0
        if off_road:
            if not self.in_glance:
                self.last = 0.0
            meters = state.trip.speed_kmh / 3.6 * dt
            self.last += meters
            self.trip += meters
        self.in_glance = off_road


class ConversationDetector:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.turns: deque[float] = deque()
        self.speaker: str | None = None
        self.last_mic: float | None = None
        self.mic_seen = False
        self.until = 0.0

    def mic(self, now: float) -> None:
        self.last_mic, self.mic_seen = now, True

    def update(self, state: State, now: float) -> bool:
        driver, passenger = state.driver.speaking, state.passenger.present and state.passenger.speaking
        speaker = "driver" if driver and not passenger else "passenger" if passenger and not driver else None
        if speaker is not None and speaker != self.speaker:
            if self.speaker is not None:
                self.turns.append(now)
            self.speaker = speaker
        while self.turns and self.turns[0] < now - float(th("conversation", "window_s")):
            self.turns.popleft()
        recent_mic = self.last_mic is not None and now - self.last_mic <= float(th("conversation", "mic_recent_s"))
        if len(self.turns) >= int(th("conversation", "min_turns")) and (recent_mic or not self.mic_seen):
            self.until = now + float(th("conversation", "hold_s"))
        return now < self.until
