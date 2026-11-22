"""Pre-generate the assistant's critical audio clips with edge-tts (plan C3, E7, D10).

Alarms and safety sentences must play in under 300 ms with no network (plan
section 5, rule 1), so they are generated once, ahead of time, as mp3 files:

* ``alarm_<name>.mp3``                 - "ANDREI!" for every person (plan C3), the fallback
* ``alarm_<alert>_<n>_<name>.mp3``     - "ANDREI! Trezește-te!": per alert, several variants (C3)
* ``alarm_repeat_<alert>_<name>.mp3``  - "ANDREI! A doua oară! Hai să oprim." (the same alert again soon)
* ``passenger_wake_<p>_<d>.mp3``       - "Maria, te rog, vorbește puțin cu Andrei..." (after a microsleep)
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
``/sounds/clips/<id>.mp3``) plus ``clips.json``, a manifest ``{id: {file, text, duration_s}}``
that core and the dashboard can read. ``duration_s`` lets core time the SOS question after an
alarm of any length (the fixed ``sos.alarm_clip_s`` is only the fallback).

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


#: MPEG audio tables for mp3_duration_s (Layer III): bitrate kbps by index, sample rates by version.
_BITRATES = {
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],  # MPEG-1
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],      # MPEG-2 / 2.5
}
_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_duration_s(data: bytes) -> float:
    """Length of an MP3 (Layer III) in seconds, by walking its frames (edge-tts: MPEG-2, 24 kHz, 48 kbps).

    Returns 0.0 when no frame is found (core then uses its fixed fallback).
    """
    pos = 0
    if data[:3] == b"ID3" and len(data) >= 10:  # skip an ID3v2 tag (its size is "syncsafe": 7 bits per byte)
        size = data[6:10]
        pos = 10 + ((size[0] & 0x7F) << 21 | (size[1] & 0x7F) << 14 | (size[2] & 0x7F) << 7 | (size[3] & 0x7F))
    seconds = 0.0
    while pos + 4 <= len(data):
        b1, b2 = data[pos + 1], data[pos + 2]
        if data[pos] != 0xFF or (b1 & 0xE0) != 0xE0:
            pos += 1
            continue
        version_bits = (b1 >> 3) & 0x03  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
        layer_bits = (b1 >> 1) & 0x03  # 1 = Layer III
        bitrate_index, rate_index, padding = (b2 >> 4) & 0x0F, (b2 >> 2) & 0x03, (b2 >> 1) & 0x01
        if version_bits == 1 or layer_bits != 1 or bitrate_index in (0, 15) or rate_index == 3:
            pos += 1
            continue
        mpeg1 = version_bits == 3
        bitrate = _BITRATES[1 if mpeg1 else 2][bitrate_index] * 1000
        sample_rate = _SAMPLE_RATES[version_bits][rate_index]
        samples = 1152 if mpeg1 else 576
        length = (144 if mpeg1 else 72) * bitrate // sample_rate + padding
        if length <= 0:
            break
        seconds += samples / sample_rate
        pos += length
    return round(seconds, 2)


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
        for alert, variants in (texts.get("alarm_alert") or {}).items():
            for number, variant in enumerate(variants, start=1):
                clips[f"alarm_{alert}_{number}_{slug(name)}"] = (fill(variant, NAME=name.upper()), True)
        for alert, text in (texts.get("alarm_repeat") or {}).items():
            clips[f"alarm_repeat_{alert}_{slug(name)}"] = (fill(text, NAME=name.upper()), True)
    for passenger, driver in permutations(names, 2):
        clips[f"passenger_instructions_{slug(passenger)}_{slug(driver)}"] = (
            fill(texts["passenger_instructions"], passenger=passenger, driver=driver), True)
        if texts.get("passenger_wake"):
            clips[f"passenger_wake_{slug(passenger)}_{slug(driver)}"] = (
                fill(texts["passenger_wake"], passenger=passenger, driver=driver), True)
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
        manifest[clip_id] = {"file": path.name, "text": text, "duration_s": mp3_duration_s(path.read_bytes())}
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
