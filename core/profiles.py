"""Driver profiles, written by P4's profile page: ``profiles/<name>/profile.json``.

The fields core reads (P4's format, the plan's section 4.F / roluri/P4): ``name``, ``safe_contact.name``,
``emergency_contact.name``, ``consent.safe_contact_notify``, ``announce``. Phone numbers are never in a profile: they
are only in ``.env`` (``SAFE_CONTACT_NUMBER``, ``EMERGENCY_NUMBER``) and only the phone bridge reads them.

A file is re-read when its modification time changes, so a change on the profile page applies without a restart.
A missing or broken file means "no profile": nothing is sent to anyone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("drivemate.core.profiles")

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"

_cache: dict[Path, tuple[float, dict[str, Any] | None]] = {}


def load(name: str, root: Path | None = None) -> dict[str, Any] | None:
    """The profile of ``name`` (lower case folder), or None."""
    path = (root or PROFILES_DIR) / name.lower() / "profile.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        log.warning("profile %s not readable: %s", path, exc)
        profile = None
    _cache[path] = (mtime, profile)
    return profile


def safe_contact(profile: dict[str, Any] | None) -> dict[str, Any]:
    """The ``state.safe_contact`` fields that come from the profile."""
    profile = profile or {}
    contact = profile.get("safe_contact") or {}
    name = str(contact.get("name") or "").strip() or None
    consent = profile.get("consent") or {}
    return {
        "name": name,
        "configured": name is not None,
        "consent": bool(consent.get("safe_contact_notify", False)),
        "announce": bool(profile.get("announce", True)),
    }
