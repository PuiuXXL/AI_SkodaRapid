"""Perception (P1) side of the core boundary: P1 still sends exactly the golden messages, handles every command core
sends, and announces (docs/perception.md §9, ``CONTRACT:`` lines) every field the contract does not declare yet.

Needs the perception runtime (numpy, OpenCV, MediaPipe import), but no camera and no model files.
"""

from __future__ import annotations

import re
import types
import typing
from typing import Any

import pytest

pytest.importorskip("cv2", reason="needs the perception runtime (requirements/p1-perception.txt)")

from pydantic import BaseModel

from shared import contracts as c
from tests.contract import make_fixtures as mf
from tests.contract.conftest import FRAME_FIXTURES, ROOT, load_fixture

REGENERATE = "run `python tests/contract/make_fixtures.py`, review the diff and tell P2 (docs/perception.md §9)"


def _paths(obj: Any, path: str = "") -> set[str]:
    """Every key path of a JSON value (lists as ``[]``): the shape of a message, without its values."""
    if isinstance(obj, dict):
        out = {path} if path else set()
        for key, value in obj.items():
            out |= _paths(value, f"{path}.{key}" if path else key)
        return out
    if isinstance(obj, list):
        out = {path}
        for item in obj:
            out |= _paths(item, f"{path}[]")
        return out
    return {path}


@pytest.fixture(scope="module")
def built() -> dict[str, Any]:
    import logging

    logging.disable(logging.WARNING)
    try:
        return mf.build_all()
    finally:
        logging.disable(logging.NOTSET)


@pytest.mark.parametrize("name", FRAME_FIXTURES)
def test_frames_have_the_golden_shape(built: dict[str, Any], name: str) -> None:
    got, want = _paths(built[name]), _paths(load_fixture(name))
    assert got == want, f"{name}: added {sorted(got - want)}, removed {sorted(want - got)}; {REGENERATE}"


def test_other_messages_match_the_golden_ones(built: dict[str, Any]) -> None:
    def summary(messages: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [(m["type"], m.get("cmd"), m.get("status"), tuple(sorted(_paths(m)))) for m in messages]

    assert summary(built["p1_messages"]) == summary(load_fixture("p1_messages")), REGENERATE


def test_built_messages_are_valid_for_the_contract(built: dict[str, Any]) -> None:
    for name in FRAME_FIXTURES:
        assert isinstance(c.parse_perception_message(built[name]), c.PerceptionFrame)
    for message in built["p1_messages"]:
        c.parse_perception_message(message)


def test_p1_parses_every_command_core_sends() -> None:
    from perception.contract import parse_command

    for raw in load_fixture("core_commands"):
        cmd = parse_command(raw)
        assert cmd.cmd == raw["cmd"]
        for key in ("open", "to", "on", "profile", "name", "quick", "camera"):
            assert getattr(cmd, key) == raw.get(key), (key, raw)


# --- fields P1 sends that the contract does not declare must be announced -------------------------------------------


def _models(annotation: Any) -> list[type[BaseModel]]:
    """BaseModel classes inside an annotation (``X | None``, ``Annotated[X, ...]``, ``list[X]`` excluded)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _models(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return [m for arg in typing.get_args(annotation) for m in _models(arg)]
    return []


def _container_item(annotation: Any, kind: type) -> Any | None:
    """The item annotation of ``list[X]`` / the value annotation of ``dict[str, X]`` (through ``| None``)."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _container_item(typing.get_args(annotation)[0], kind)
    if origin in (typing.Union, types.UnionType):
        for arg in typing.get_args(annotation):
            found = _container_item(arg, kind)
            if found is not None:
                return found
        return None
    if origin is kind:
        args = typing.get_args(annotation)
        return args[-1] if args else Any
    return None


def _field(model: type[BaseModel], key: str) -> Any | None:
    for name, info in model.model_fields.items():
        if key in (name, info.alias):
            return info
    return None


def undeclared(value: Any, annotation: Any, path: str = "") -> list[str]:
    """Paths in ``value`` that the contract model ``annotation`` does not declare (the highest one of each branch)."""
    models = _models(annotation)
    if isinstance(value, dict) and models:
        out: list[str] = []
        for key, item in value.items():
            sub = f"{path}.{key}" if path else key
            info = next((f for m in models if (f := _field(m, key)) is not None), None)
            out += [sub] if info is None else undeclared(item, info.annotation, sub)
        return out
    if isinstance(value, dict) and (inner := _container_item(annotation, dict)) is not None:
        return [p for key, item in value.items() for p in undeclared(item, inner, f"{path}.*")]
    if isinstance(value, list) and (inner := _container_item(annotation, list)) is not None:
        return [p for item in value for p in undeclared(item, inner, f"{path}[]")]
    return []


def announced() -> set[str]:
    """Field paths of the ``CONTRACT: <path>, ...`` lines in docs/perception.md."""
    text = (ROOT / "docs" / "perception.md").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^CONTRACT:\s*([A-Za-z_][\w.\[\]*]*)\s*,", text, re.MULTILINE)}


def test_fields_missing_from_the_contract_are_announced() -> None:
    frame = load_fixture("p1_frame_full")
    extra = sorted(set(undeclared(frame, c.PerceptionFrame)))
    missing = [p for p in extra if p not in announced()]
    assert not missing, (
        f"P1 sends fields that shared/contracts.py does not declare and docs/perception.md §9 does not announce: "
        f"{missing}. Add one `CONTRACT: <path>, <type> (default ...), P1, <why>` line per field and tell P2."
    )
