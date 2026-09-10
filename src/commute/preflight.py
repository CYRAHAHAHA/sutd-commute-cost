from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def evenly_spaced_sample(rows: Sequence[Any], sample_size: int) -> list[Any]:
    """Select deterministic rows spread across the provider's ordered population."""
    if sample_size <= 0 or not rows:
        return []
    if sample_size >= len(rows):
        return list(rows)
    if sample_size == 1:
        return [rows[len(rows) // 2]]
    indexes = [round(index * (len(rows) - 1) / (sample_size - 1)) for index in range(sample_size)]
    return [rows[index] for index in indexes]
