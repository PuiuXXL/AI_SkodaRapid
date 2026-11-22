"""Short spoken quiz, the alternative when the driver refuses music (plan D8).

"Pare monoton. Pun ceva mai energic?" -> "Nu." -> "Bine. Vrei un quiz scurt?" ->
"Da." -> a few one-line questions answered by voice. Answering keeps the driver
mentally engaged without anything to read (plan principle 2); P2 measures the
effect on disengagement like for any intervention (plan D6).

Questions live in ``assistant/data/quiz.json`` (each <= 15 words, short spoken
answers). The quiz length comes from ``quiz.length`` in assistant.yaml.
This module is pure logic; the conversation is driven by ``assistant/dialog.py``.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from functools import lru_cache

from assistant.settings import cfg, resolve_path
from assistant.textutil import normalize

log = logging.getLogger("drivemate.assistant.quiz")


@dataclass(frozen=True)
class Question:
    """One quiz question.

    Attributes:
        q: The spoken question.
        answers: Accepted answers, normalised (no diacritics, lower-case).
        say: How the right answer is said when the driver misses it.
        kid_safe: May be asked with a child on board.
    """

    q: str
    answers: tuple[str, ...]
    say: str
    kid_safe: bool = True


@lru_cache(maxsize=1)
def load_questions() -> tuple[Question, ...]:
    """Load and cache ``quiz.questions_file`` (empty tuple if missing, logged)."""
    path = resolve_path(cfg("quiz", "questions_file", default="assistant/data/quiz.json"))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Quiz questions not loaded (%s): quiz disabled.", exc)
        return ()
    return tuple(
        Question(q=item["q"], answers=tuple(normalize(a) for a in item["a"]),
                 say=item.get("say", item["a"][0]), kid_safe=bool(item.get("kid_safe", True)))
        for item in raw.get("questions", []) if item.get("q") and item.get("a")
    )


def is_correct(question: Question, text: str) -> bool:
    """True if the spoken answer contains one of the accepted answers as whole words.

    Args:
        question: The question asked.
        text: What the driver said ("cred că Paris", "e Dunărea").
    """
    spoken = f" {normalize(text)} "
    return any(f" {answer} " in spoken for answer in question.answers)


class QuizSession:
    """One quiz: a few random questions, a running score."""

    def __init__(self, kid_safe_only: bool = False, length: int | None = None, seed: int | None = None) -> None:
        """Pick the questions.

        Args:
            kid_safe_only: Only ``kid_safe`` questions (child on board, plan G4).
            length: Number of questions; defaults to ``quiz.length`` (3).
            seed: Random seed (tests).
        """
        pool = [q for q in load_questions() if q.kid_safe or not kid_safe_only]
        count = min(length or int(cfg("quiz", "length", default=3)), len(pool))
        self.questions: list[Question] = random.Random(seed).sample(pool, count)
        self.index = 0
        self.score = 0

    @property
    def total(self) -> int:
        """Number of questions in this quiz."""
        return len(self.questions)

    @property
    def current(self) -> Question | None:
        """The question waiting for an answer, or None when the quiz is over."""
        return self.questions[self.index] if self.index < len(self.questions) else None

    def answer(self, text: str) -> tuple[bool, Question]:
        """Score the answer to the current question and move to the next one.

        Args:
            text: The driver's spoken answer.

        Returns:
            ``(correct, question_answered)``.

        Raises:
            IndexError: If the quiz is already over.
        """
        question = self.current
        if question is None:
            raise IndexError("quiz is over")
        correct = is_correct(question, text)
        self.score += int(correct)
        self.index += 1
        return correct, question
