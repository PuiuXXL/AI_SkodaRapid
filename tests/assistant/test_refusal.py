"""Tests for assistant.refusal.is_refusal (plan D10: ~30 phrases, < 1 ms, with/without diacritics)."""

import time

import pytest

from assistant.refusal import is_refusal

REFUSALS = [
    "Lasă-mă în pace.",
    "lasa ma in pace",
    "LASĂ-MĂ ÎN PACE!",
    "Lasă-mă!",
    "Lasă.",
    "lasa",
    "Taci.",
    "taci odată",
    "Nu acum.",
    "nu acum, te rog",
    "Nu vreau.",
    "nu vreau să vorbesc",
    "N-am chef.",
    "Nu am chef de vorbă",
    "Nu mă interesează.",
    "Mai târziu.",
    "Stop.",
    "Gata.",
    "Ajunge!",
    "Liniște!",
    "Încetează.",
    "Lăsați-mă în pace",
    "Nu mai vorbi.",
    "Leave me alone",
    "not now",
]

NOT_REFUSALS = [
    "Da.",
    "Da, sunt cam obosit.",
    "Cinci.",
    "Lasă telefonul pe bord",
    "Pune ceva muzică",
    "Spune-i că ajung în 20 de minute.",
    "Nu vreau să dorm, hai să vorbim",
    "Amintește-mi să iau lichid de parbriz",
    "Când ajungem?",
    "",
    "   ",
]


@pytest.mark.parametrize("text", REFUSALS)
def test_refusals_are_detected(text):
    assert is_refusal(text) is True


@pytest.mark.parametrize("text", NOT_REFUSALS)
def test_non_refusals_are_ignored(text):
    assert is_refusal(text) is False


def test_cedilla_diacritics_are_accepted():
    # Legacy cedilla forms (ş ţ) produced by some phones / recognisers.
    assert is_refusal("Linişte!") is True


def test_under_one_millisecond():
    phrases = REFUSALS + NOT_REFUSALS
    started = time.perf_counter()
    for _ in range(100):
        for phrase in phrases:
            is_refusal(phrase)
    per_call_ms = (time.perf_counter() - started) * 1000 / (100 * len(phrases))
    assert per_call_ms < 1.0
