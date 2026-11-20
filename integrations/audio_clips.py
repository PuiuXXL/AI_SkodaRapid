"""Pre-generate the assistant's critical audio clips with edge-tts (plan C3, E7, D10).

Alarms and safety sentences must play in under 300 ms with no network (plan
section 5, rule 1), so they are generated once, ahead of time, as mp3 files:

* ``alarm_<name>.mp3``                 - "ANDREI!" for every person (plan C3)
* ``are_you_ok.mp3``                   - "Ești bine?" (C4)
* ``passenger_instructions_<p>_<d>.mp3`` - instructions for passenger <p> when driver <d>
                                         does not answer (C5); never "grab the wheel"
* ``monitoring_lost.mp3``              - "Nu te mai văd..." (C7)
* ``refusal_ack.mp3``                  - "Ok, te las în pace." (D10)
* ``notify_contact_<contact>.mp3``     - "Îi dau de veste lui Mihai." (C10)
* ``resume.mp3``                       - "...cum ziceam," (D4)
* ``message_deferred.mp3``             - "Ți-l citesc imediat ce e liniște." (F2)
* ``confirm_*.mp3``                    - short confirmations ("Notat.", "Trimis."...)

Output: ``dashboard/public/sounds/clips/`` (served by the dashboard at
``/sounds/clips/<id>.mp3``) plus ``clips.json``, a manifest ``{id: {file, text}}``
that core and the dashboard can read.

Texts come from ``assistant/config/texts.<language>.yaml`` (group ``clips``).
Names come from ``profiles/*/profile.json`` when P4 has created them, otherwise
from ``clips.names`` / ``clips.contact_names`` in ``assistant.yaml``.

Usage (needs internet, run once and after changing names or texts)::

    .venv/Scripts/python integrations/audio_clips.py          # Windows
    .venv/bin/python integrations/audio_clips.py              # Linux / macOS
    ... integrations/audio_clips.py --force                   # regenerate everything
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from itertools import permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant.settings import cfg, get_texts, resolve_path  # noqa: E402
from assistant.textutil import fill, normalize  # noqa: E402
from assistant.tts import default_voice, synthesize  # noqa: E402


def slug(name: str) -> str:
    """File-name-safe version of a name: ``"Ana Maria"`` -> ``"ana_maria"``."""
    return normalize(name).replace(" ", "_")


def load_names() -> tuple[list[str], list[str]]:
    """People and trusted contacts that need personal clips.

    Returns:
        ``(names, contact_names)``. Profiles (``profiles/<id>/profile.json``) are
        added to the configured lists; a profile may contain ``"name"`` and a
        ``"safe_contact": {"name": ...}`` / ``"emergency_contact": {"name": ...}``.
    """
    names = list(cfg("clips", "names", default=[]))
    contacts = list(cfg("clips", "contact_names", default=[]))
    for profile_file in sorted((ROOT / "profiles").glob("*/profile.json")):
        try:
            data = json.loads(profile_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = data.get("name") or profile_file.parent.name.capitalize()
        names.append(name)
        for key in ("safe_contact", "emergency_contact"):
            contact = data.get(key) or {}
            if isinstance(contact, dict) and contact.get("name"):
                contacts.append(contact["name"])
    unique = lambda items: list(dict.fromkeys(items))  # noqa: E731 - keep order, drop duplicates
    return unique(names), unique(contacts)


def build_clip_list() -> dict[str, tuple[str, bool]]:
    """All clips to generate.

    Returns:
        ``{clip_id: (text, is_alarm)}``; alarms use the faster ``tts.alarm_rate``.
    """
    texts = get_texts().get("clips", {})
    names, contacts = load_names()
    clips: dict[str, tuple[str, bool]] = {}
    for name in names:
        clips[f"alarm_{slug(name)}"] = (fill(texts["alarm_name"], NAME=name.upper()), True)
    for passenger, driver in permutations(names, 2):
        clips[f"passenger_instructions_{slug(passenger)}_{slug(driver)}"] = (
            fill(texts["passenger_instructions"], passenger=passenger, driver=driver), True)
    for contact in contacts:
        clips[f"notify_contact_{slug(contact)}"] = (fill(texts["notify_contact"], contact=contact), False)
    for key in ("are_you_ok", "monitoring_lost", "refusal_ack", "resume", "message_deferred"):
        clips[key] = (texts[key], key in ("are_you_ok", "monitoring_lost"))
    for key, value in texts.items():
        if key.startswith("confirm_"):
            clips[key] = (value, False)
    return clips


async def generate(force: bool = False) -> dict[str, dict[str, str]]:
    """Generate missing clips (all of them with ``force``) and write ``clips.json``.

    Args:
        force: Regenerate files that already exist.

    Returns:
        The manifest written to ``clips.json``.
    """
    out_dir = resolve_path(cfg("clips", "output_dir", default="dashboard/public/sounds/clips"))
    out_dir.mkdir(parents=True, exist_ok=True)
    voice = default_voice()
    manifest: dict[str, dict[str, str]] = {}
    for clip_id, (text, is_alarm) in build_clip_list().items():
        path = out_dir / f"{clip_id}.mp3"
        rate = cfg("tts", "alarm_rate", default="+15%") if is_alarm else cfg("tts", "rate", default="+0%")
        if force or not path.exists():
            path.write_bytes(await synthesize(text, voice, rate))
            print(f"  generated {path.name:45s} {text}")
        manifest[clip_id] = {"file": path.name, "text": text}
    (out_dir / "clips.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(manifest)} clips in {out_dir} (voice {voice})")
    return manifest


def main() -> None:
    """Command-line entry point (see module docstring)."""
    # Windows consoles default to cp1252, which cannot print Romanian diacritics.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Pre-generate DriveMate audio clips with edge-tts.")
    parser.add_argument("--force", action="store_true", help="regenerate clips that already exist")
    args = parser.parse_args()
    asyncio.run(generate(force=args.force))


if __name__ == "__main__":
    main()
