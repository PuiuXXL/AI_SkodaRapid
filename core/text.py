"""Small formatting helpers for the fixed Romanian texts."""

from __future__ import annotations


def seconds(value: float) -> str:
    """Seconds with one decimal and a comma, as spoken and written in Romanian: 2.14 -> "2,1"."""
    return f"{value:.1f}".replace(".", ",")
