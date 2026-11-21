"""Configuration of core (P2): ``core/config/thresholds.yaml`` and ``core/config/templates.yaml``.

The plan forbids thresholds in code (section 8), so core reads every value through :func:`th` and every fixed text
through :func:`render`.

* ``demo_mode: true`` merges the ``demo:`` block of ``thresholds.yaml`` over the normal values. A key in ``demo:``
  that does not exist above it is an error (a typo must not silently keep the long window).
* :func:`render` fills a template with ``str.format``; a missing field is an error, never a half-filled SMS.

Values are cached; tests call :func:`reload` after changing a file.
"""

from __future__ import annotations

import copy
import string
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR: Path = Path(__file__).resolve().parent / "config"
THRESHOLDS_FILE: Path = CONFIG_DIR / "thresholds.yaml"
TEMPLATES_FILE: Path = CONFIG_DIR / "templates.yaml"

_MISSING = object()


class ConfigError(ValueError):
    """The configuration is inconsistent (unknown demo key, missing template, missing field)."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: the top level must be a mapping")
    return data


def merge_overrides(base: dict[str, Any], overrides: dict[str, Any], path: str = "demo") -> dict[str, Any]:
    """``base`` with ``overrides`` merged in (deep, new dict). Every override key must already exist in ``base``."""
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        where = f"{path}.{key}"
        if key not in merged:
            raise ConfigError(f"thresholds.yaml: {where} overrides a key that does not exist")
        if isinstance(value, dict):
            if not isinstance(merged[key], dict):
                raise ConfigError(f"thresholds.yaml: {where} is a mapping, the normal value is not")
            merged[key] = merge_overrides(merged[key], value, where)
        else:
            merged[key] = value
    return merged


def load_thresholds(path: Path = THRESHOLDS_FILE, demo: bool | None = None) -> dict[str, Any]:
    """Parse ``thresholds.yaml``; ``demo`` overrides ``demo_mode`` from the file (None = use the file)."""
    raw = _load_yaml(path)
    overrides = raw.pop("demo", None) or {}
    use_demo = raw.get("demo_mode", False) if demo is None else demo
    if use_demo:
        raw = merge_overrides(raw, overrides)
    else:
        merge_overrides(raw, overrides)  # still validate the demo block
    raw["demo_mode"] = bool(use_demo)
    return raw


@lru_cache(maxsize=1)
def thresholds() -> dict[str, Any]:
    """The thresholds in use (cached)."""
    return load_thresholds()


@lru_cache(maxsize=1)
def templates() -> dict[str, Any]:
    """The fixed texts (cached)."""
    return _load_yaml(TEMPLATES_FILE)


def _get(tree: dict[str, Any], keys: tuple[str, ...], default: Any, source: str) -> Any:
    node: Any = tree
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            if default is _MISSING:
                raise KeyError(f"{source}: {'.'.join(keys)} is not set")
            return default
        node = node[key]
    return node


def th(*keys: str, default: Any = _MISSING) -> Any:
    """One threshold, e.g. ``th("sos", "countdown_s")``. A missing key raises unless ``default`` is given."""
    return _get(thresholds(), keys, default, "thresholds.yaml")


def template(*keys: str) -> Any:
    """One raw template (or group of templates), e.g. ``template("sos", "passenger_state")``."""
    return _get(templates(), keys, _MISSING, "templates.yaml")


def template_fields(text: str) -> set[str]:
    """The ``{field}`` names a template uses."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def render(*keys: str, **fields: Any) -> str:
    """Fill a template, e.g. ``render("reminders", "due", task="lichid de parbriz")``.

    Raises:
        ConfigError: the template does not exist, is not a string, or a field is missing.
    """
    try:
        text = template(*keys)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc
    if not isinstance(text, str):
        raise ConfigError(f"templates.yaml: {'.'.join(keys)} is not a text")
    missing = template_fields(text) - fields.keys()
    if missing:
        raise ConfigError(f"templates.yaml: {'.'.join(keys)} needs {', '.join(sorted(missing))}")
    return text.format(**fields)


def reload() -> None:
    """Forget the cached files (tests, or after editing a yaml while core runs)."""
    thresholds.cache_clear()
    templates.cache_clear()
