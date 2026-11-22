"""Driver preferences that change HOW the assistant interacts (not what is safe).

Three preferences, each one a list of allowed values under ``preferences:`` in
``assistant/config/assistant.yaml``:

* ``talkativeness`` (``low`` / ``normal`` / ``high``) - how often COMFORT suggestions
  (``driver_preferences.comfort_events``, e.g. music against disengagement) may come.
  Cause and fatigue interventions keep the normal rate: safety never depends on it.
* ``follow_up`` (``always`` / ``never``) - whether "Te mai ajut cu ceva?" is added
  after a statement that answers the driver (``assistant/client.py``).
* ``answer_length`` (``short`` / ``normal``) - the word count the LLM is asked to aim
  for. The hard limit stays ``speech.max_words_to_driver``, so a slightly longer
  answer is not thrown away for a fixed text.

Where a value comes from, last one wins:

1. ``driver_preferences.defaults`` in ``assistant.yaml``;
2. ``preferences`` in ``profiles/<driver>/profile.json`` (P4's file, edited by hand
   while there is no profile page: the permanent choice);
3. a change for the current trip only (:meth:`PreferenceStore.reset` on a new trip): a
   confirmed ``set_preference`` said by voice ("răspunde mai scurt" -> "Bine?" -> "da"; known
   phrases are recognised without the LLM by :func:`voice_command`) or a choice on the
   dashboard's settings page. Core records both, after its own check.

Values that are not allowed by ``assistant.yaml`` are ignored at every level, so a
hand-edited profile can never put the assistant in an unknown mode.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from assistant import cabin
from assistant.contract import Action, State
from assistant.settings import REPO_ROOT, cfg
from assistant.textutil import normalize

log = logging.getLogger("drivemate.assistant.preferences")

#: Preferences handled by this module (other ``set_preference`` keys, e.g. volume, belong to core).
KEYS: tuple[str, ...] = ("talkativeness", "follow_up", "answer_length")

#: Built-in defaults, used only if ``driver_preferences.defaults`` is missing from assistant.yaml.
_BUILTIN_DEFAULTS: dict[str, str] = {"talkativeness": "normal", "follow_up": "always", "answer_length": "normal"}

#: Folder with ``<profile>/profile.json`` (P4). Tests point it at a temporary folder.
PROFILES_DIR: Path = REPO_ROOT / "profiles"

#: ``path -> (mtime, parsed profile)``: the file is read again only after it changes.
_profile_cache: dict[Path, tuple[float, dict[str, Any]]] = {}


def _allowed(key: str, value: Any) -> bool:
    """True when ``value`` is in the list of allowed values of ``preferences.<key>``."""
    allowed = cfg("preferences", key, default=None)
    return isinstance(allowed, list) and value in allowed


def driver_profile(state: State) -> dict[str, Any]:
    """The driver's ``profiles/<profile>/profile.json`` as a dict (``{}`` when unknown or missing).

    Shared by this module and :func:`assistant.music.profile_genres`. The parsed file is
    cached and read again only when its modification time changes, so calling this for
    every event costs one ``stat``.

    Args:
        state: Current state (the driver occupant gives the profile id).

    Returns:
        The parsed profile, or an empty dict.
    """
    person = cabin.occupant(state, "driver")
    if person is None or not person.profile:
        return {}
    path = PROFILES_DIR / person.profile / "profile.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _profile_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", path, exc)
        return {}
    data = data if isinstance(data, dict) else {}
    _profile_cache[path] = (mtime, data)
    return data


def _profile_key(state: State | None) -> str:
    """Key under which voice changes are kept: the driver's profile id, ``""`` when unknown."""
    if state is None:
        return ""
    person = cabin.occupant(state, "driver")
    return person.profile if person is not None and person.profile else ""


class PreferenceStore:
    """Effective preferences per driver: defaults, then profile, then voice changes of this trip.

    One process-wide instance (:data:`store`) is shared by the client (summary, policies,
    follow-up) and :class:`assistant.dialog.DialogManager` (which records a confirmed
    ``set_preference``), because core creates those two objects separately.
    """

    def __init__(self) -> None:
        """Start with no voice changes."""
        self._voice: dict[str, dict[str, str]] = {}
        self._last_key: str = ""

    def effective(self, state: State) -> dict[str, str]:
        """Return the value of every key in :data:`KEYS` for the current driver.

        Args:
            state: Current state.

        Returns:
            e.g. ``{"talkativeness": "low", "follow_up": "always", "answer_length": "short"}``.
        """
        configured = cfg("driver_preferences", "defaults", default=None) or {}
        result = {key: str(configured.get(key, _BUILTIN_DEFAULTS[key])) for key in KEYS}
        stored = driver_profile(state).get("preferences")
        if isinstance(stored, dict):
            result.update({k: str(v) for k, v in stored.items() if k in KEYS and _allowed(k, v)})
        key = _profile_key(state)
        self._last_key = key
        result.update(self._voice.get(key, {}))
        return result

    def apply(self, action: Action, state: State | None = None) -> bool:
        """Remember a ``set_preference`` the driver confirmed (or that needs no confirmation).

        Only keys of :data:`KEYS` with an allowed value are kept; anything else (volume,
        music_genre) is left to core and ignored here.

        Args:
            action: The ``set_preference`` action being executed.
            state: Current state; ``None`` uses the driver seen by the last :meth:`effective`.

        Returns:
            True when the preference was stored.
        """
        if action.type != "set_preference" or action.key not in KEYS or not _allowed(action.key, action.value):
            return False
        key = _profile_key(state) if state is not None else self._last_key
        self._voice.setdefault(key, {})[action.key] = str(action.value)
        log.info("preference %s=%s for %s (voice, this trip)", action.key, action.value, key or "unknown driver")
        return True

    def reset(self) -> None:
        """Forget the voice changes (new trip / director reset); the profile values stay."""
        self._voice.clear()


#: The process-wide store (see :class:`PreferenceStore`).
store = PreferenceStore()


def effective(state: State) -> dict[str, str]:
    """Shortcut for ``store.effective(state)``."""
    return store.effective(state)


def comfort_interval_s(state: State) -> float | None:
    """Minimum seconds between two comfort suggestions for this driver's ``talkativeness``.

    Returns:
        ``driver_preferences.comfort_interval_s.<talkativeness>``, or None when it is not
        configured (the normal ``policies.proactive_min_interval_s`` then applies).
    """
    value = cfg("driver_preferences", "comfort_interval_s", effective(state)["talkativeness"], default=None)
    return float(value) if value is not None else None


def answer_words(state: State) -> int | None:
    """Word count the LLM should aim for (``answer_length``), or None for no extra target."""
    value = cfg("driver_preferences", "answer_words", effective(state)["answer_length"], default=None)
    return int(value) if value is not None else None


def voice_command(text: str) -> tuple[str, str] | None:
    """A preference asked by voice in a known phrase ("răspunde mai scurt"), recognised without the LLM.

    The phrases are in ``driver_preferences.voice_commands`` (normalised). One must appear as consecutive
    words in an utterance of at most ``driver_preferences.voice_max_words`` words; the value must be allowed
    by ``preferences.<key>``. Free wordings ("nu mai vorbi atât") are left to the LLM.

    Args:
        text: What the driver said (wake word included or not).

    Returns:
        ``(key, value)``, e.g. ``("answer_length", "short")``, or None.
    """
    tokens = normalize(text).split()
    if not tokens or len(tokens) > int(cfg("driver_preferences", "voice_max_words", default=12)):
        return None
    padded = " " + " ".join(tokens) + " "
    for command in cfg("driver_preferences", "voice_commands", default=[]) or []:
        key, value = command.get("key"), command.get("value")
        if key not in KEYS or not _allowed(key, value):
            continue
        if any(" " + normalize(phrase) + " " in padded for phrase in command.get("phrases", [])):
            return str(key), str(value)
    return None


def follow_up_enabled(state: State) -> bool:
    """False when the driver asked not to hear "Te mai ajut cu ceva?" (``follow_up: never``)."""
    return effective(state)["follow_up"] != "never"
