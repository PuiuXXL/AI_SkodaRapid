"""Tests for core/config/thresholds.yaml, core/config/templates.yaml and core/settings.py."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from core import settings
from shared import contracts as c

# Keys the role file asks for (roluri/P2-context-siguranta.md, step 1).
REQUIRED_KEYS = [
    ("demo_mode",),
    ("safety", "microsleep", "closed_ms"),
    ("safety", "distraction", "off_road_ms"),
    ("safety", "distraction", "phone_min_ms"),
    ("safety", "escalation", "alarm_after_ms"),
    ("safety", "monitoring", "lost_after_ms"),
    ("fatigue", "weights"),
    ("disengagement", "weights"),
    ("fatigue", "window_s"),
    ("attention", "window_s"),
    ("cause", "window_s"),
    ("intervention", "before_s"),
    ("refusal_mute_min",),
    ("safe_contact", "fatigue_min"),
    ("safe_contact", "cooldown_min"),
    ("sos", "countdown_s"),
]

# The plan's formulas (section 4.B).
F_TERMS = {"perclos", "blink_duration", "yawn", "slow_reaction", "nodding", "trip_duration"}
D_TERMS = {"slow_reaction", "low_entropy", "low_response_rate", "short_answers", "monotony"}


@pytest.fixture(autouse=True)
def _fresh() -> typing.Iterator[None]:
    settings.reload()
    yield
    settings.reload()


@pytest.mark.parametrize("keys", REQUIRED_KEYS, ids=lambda k: ".".join(k))
def test_required_keys_exist(keys: tuple[str, ...]) -> None:
    settings.th(*keys)


def test_missing_key_raises_unless_default() -> None:
    with pytest.raises(KeyError):
        settings.th("safety", "no_such_rule")
    assert settings.th("safety", "no_such_rule", default=7) == 7


@pytest.mark.parametrize(("block", "terms"), [("fatigue", F_TERMS), ("disengagement", D_TERMS)])
def test_weights_follow_the_plan_formula(block: str, terms: set[str]) -> None:
    weights = settings.th(block, "weights")
    assert set(weights) == terms
    assert sum(weights.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("block", ["fatigue", "disengagement"])
def test_every_term_has_a_valid_range(block: str) -> None:
    weights, norm = settings.th(block, "weights"), settings.th(block, "norm")
    assert set(norm) <= set(weights)
    assert set(weights) - set(norm) <= {"monotony"}  # a context flag, not a measured value
    for low, high in norm.values():
        assert low != high


def test_score_thresholds_have_hysteresis() -> None:
    for block in ("fatigue", "disengagement"):
        assert 0 < settings.th(block, "low") < settings.th(block, "high") <= 1


def test_microsleep_is_longer_than_a_blink() -> None:
    # P1 calls a closure longer than eyes.blink_max_ms (500 ms) a closure, not a blink.
    assert settings.th("safety", "microsleep", "closed_ms") > 500


def test_tuning_never_touches_safety_rules() -> None:
    """C8: thumbs down adjusts only P3-P4 thresholds, within fixed limits."""
    for key, (low, high) in settings.th("tuning", "limits").items():
        assert key.split(".")[0] not in ("safety", "sos")
        assert low <= settings.th(*key.split(".")) <= high


def test_demo_mode_shortens_the_windows() -> None:
    demo = settings.load_thresholds(demo=True)
    normal = settings.load_thresholds(demo=False)
    assert demo["demo_mode"] is True and normal["demo_mode"] is False
    assert demo["refusal_mute_min"] < normal["refusal_mute_min"]
    assert demo["intervention"]["before_s"] < normal["intervention"]["before_s"]
    assert demo["safe_contact"]["fatigue_min"] == normal["safe_contact"]["fatigue_min"]  # untouched keys stay


def test_unknown_demo_key_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text("demo_mode: true\nsos:\n  countdown_s: 10\ndemo:\n  sos:\n    countdwn_s: 5\n", encoding="utf-8")
    with pytest.raises(settings.ConfigError, match="countdwn_s"):
        settings.load_thresholds(path)
    with pytest.raises(settings.ConfigError):
        settings.load_thresholds(path, demo=False)  # validated even when demo mode is off


# --- templates -------------------------------------------------------------------------------------------------------

TEMPLATE_FIELDS = {
    ("links", "maps"): {"lat", "lon"},
    ("sos", "call"): {"driver_name", "unresponsive_s", "occupants_n", "passenger_state_text", "time_hhmm"},
    ("sos", "sms"): {"driver_name", "unresponsive_s", "occupants_n", "passenger_state_text", "maps_url", "time_hhmm"},
    ("sos", "passenger_instructions"): {"passenger_name", "driver_name"},
    ("safe_contact", "sms"): {"driver_name", "elapsed_text", "maps_url", "eta_min"},
    ("safe_contact", "sms_no_eta"): {"driver_name", "elapsed_text", "maps_url"},
    ("safe_contact", "elapsed_hours"): {"h", "m"},
    ("safe_contact", "elapsed_minutes"): {"m"},
    ("reminders", "due"): {"task"},
    ("explanations", "microsleep"): {"s", "speed_kmh"},
    ("explanations", "nodding"): {"speed_kmh"},
    ("explanations", "off_road"): {"zone_text", "s", "speed_kmh"},
    ("explanations", "phone"): {"s", "speed_kmh"},
    ("explanations", "unresponsive"): {"s"},
    ("explanations", "monitoring_lost"): {"reason_text"},
}


@pytest.mark.parametrize(("keys", "fields"), list(TEMPLATE_FIELDS.items()), ids=lambda k: str(k))
def test_template_fields(keys: tuple[str, ...], fields: set[str]) -> None:
    assert settings.template_fields(settings.template(*keys)) == fields


def test_sos_sms_renders_like_the_plan() -> None:
    maps = settings.render("links", "maps", lat=45.75, lon=21.23)
    text = settings.render(
        "sos", "sms", driver_name="Andrei", unresponsive_s=15, occupants_n=2,
        passenger_state_text=settings.template("sos", "passenger_state", "awake"), maps_url=maps, time_hhmm="18:20",
    )
    assert text == (
        "Alertă automată DriveMate. Andrei nu răspunde de 15 secunde. Ocupanți: 2; pasagerul din dreapta e treaz. "
        "Locație: https://www.google.com/maps?q=45.75000,21.23000. Ora: 18:20."
    )


def test_safe_contact_sms_renders_like_the_plan() -> None:
    text = settings.render(
        "safe_contact", "sms", driver_name="Andrei", elapsed_text="1 h 14 min", maps_url="https://x", eta_min=20,
    )
    assert text.startswith("DriveMate: Andrei pare obosit (1 h 14 min la volan) și nu vrea pauză acum.")
    assert text.endswith("Ajunge în ~20 min.")


def test_call_text_has_no_link() -> None:
    assert "http" not in settings.template("sos", "call") and "{maps_url}" not in settings.template("sos", "call")


def test_missing_field_is_an_error() -> None:
    with pytest.raises(settings.ConfigError, match="task"):
        settings.render("reminders", "due")
    with pytest.raises(settings.ConfigError):
        settings.render("reminders", "no_such_template")


def test_no_phone_number_in_the_templates() -> None:
    text = settings.TEMPLATES_FILE.read_text(encoding="utf-8")
    assert not re.search(r"\+?\d[\d ]{8,}\d", text)


def test_lookup_tables_cover_the_contract_vocabularies() -> None:
    zones = settings.template("zones")
    assert set(c.GAZE_ZONES) - {"road", "unknown"} <= set(zones)
    assert set(c.MONITORING_REASONS) <= set(settings.template("monitoring_reasons"))
    states = typing.get_args(c.SosReport.model_fields["passenger_state"].annotation)
    assert set(states) == set(settings.template("sos", "passenger_state"))
