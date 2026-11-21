"""B1: the driver's reaction time on 3 channels, against the driver's own baseline.

* **visual**: from the discrete signal of an off-road distraction (C2) until the gaze is back on the road;
* **verbal**: from the end of a question (``speak_done``) to the start of the voice (``speech_onset``, WebAudio);
* **gesture**: from the end of a question to a nod / shake or a gesture.

The baseline per channel is the median of the first ``baseline_min_samples``..``baseline_max_samples`` reactions
(``default_baseline_ms`` until then). ``r = latency / baseline``; ``slow_ratio`` is the mean r of the last ``recent``
reactions. No reaction within ``missed_ms`` counts as the maximum value and ``missed += 1`` (a question without any
answer is recorded on the verbal channel).
"""

from __future__ import annotations

import statistics
from collections import deque

from core.settings import th

CHANNELS = ("visual", "verbal", "gesture")


class ReactionTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last: dict[str, float | None] = dict.fromkeys(CHANNELS)
        self.first: dict[str, list[float]] = {ch: [] for ch in CHANNELS}  # for the baseline
        self.recent: deque[tuple[str, float]] = deque(maxlen=int(th("reaction", "recent")))
        self.outcomes: deque[tuple[float, bool]] = deque()  # (t, answered) per question, for the response rate
        self.words: deque[int] = deque(maxlen=5)
        self.missed = 0
        self.question_at: float | None = None
        self.awaiting_words = False
        self.visual_since: float | None = None
        self.visual_episode: float | None = None

    def baseline(self, channel: str) -> float:
        samples = self.first[channel]
        if len(samples) >= int(th("reaction", "baseline_min_samples")):
            return float(statistics.median(samples))
        return float(th("reaction", "default_baseline_ms", channel))

    def record(self, channel: str, ms: float, *, missed: bool = False) -> None:
        self.last[channel] = round(ms, 1)
        self.recent.append((channel, ms))
        if missed:
            self.missed += 1
        elif len(self.first[channel]) < int(th("reaction", "baseline_max_samples")):
            self.first[channel].append(ms)

    def slow_ratio(self) -> float | None:
        if not self.recent:
            return None
        return statistics.fmean(ms / self.baseline(channel) for channel, ms in self.recent)

    # --- inputs --------------------------------------------------------------------------------------------------

    def question(self, now: float) -> None:
        """A question was just spoken: the verbal and gesture clocks start."""
        self.question_at = now
        self.awaiting_words = True

    def answer(self, channel: str, now: float) -> None:
        if self.question_at is None:
            return
        self.record(channel, (now - self.question_at) * 1000.0)
        self.outcomes.append((now, True))
        self.question_at = None

    def heard(self, text: str) -> None:
        """Words of the first utterance after a question (short answers, D)."""
        if self.awaiting_words and text.strip():
            self.words.append(len(text.split()))
            self.awaiting_words = False

    def visual_cue(self, started: float) -> None:
        """An off-road distraction episode started at ``started`` (one visual reaction per episode)."""
        if started != self.visual_episode:
            self.visual_episode = started
            self.visual_since = started

    def tick(self, gaze_zone: str, now: float) -> None:
        if self.visual_since is not None:
            elapsed = (now - self.visual_since) * 1000.0
            if gaze_zone == "road":
                self.record("visual", elapsed)
                self.visual_since = None
            elif elapsed >= float(th("reaction", "missed_ms", "visual")):
                self.record("visual", float(th("reaction", "missed_ms", "visual")), missed=True)
                self.visual_since = None
        if self.question_at is not None:
            limit = float(th("reaction", "missed_ms", "verbal"))
            if (now - self.question_at) * 1000.0 >= limit:
                self.record("verbal", limit, missed=True)
                self.outcomes.append((now, False))
                self.question_at = None
        window = float(th("reaction", "response_window_min")) * 60.0
        while self.outcomes and self.outcomes[0][0] < now - window:
            self.outcomes.popleft()

    # --- outputs -------------------------------------------------------------------------------------------------

    def response_rate(self) -> float | None:
        if not self.outcomes:
            return None
        return sum(1 for _, answered in self.outcomes if answered) / len(self.outcomes)

    def mean_words(self) -> float | None:
        return statistics.fmean(self.words) if self.words else None
