# utils.py
"""
utils.py - Common utility functions for Kemet

Provides shared, stateless helper functions used across different modules.
"""
from __future__ import annotations

from typing import List, Tuple

Point = Tuple[int, int]


def get_neighbors(x: int, y: int, width: int, height: int) -> List[Point]:
    """Return list of valid orthogonal neighbors for a given position."""
    options = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            options.append((nx, ny))
    return options


def clamp(val: float, low: float, high: float) -> float:
    """Clamp a value between low and high bounds."""
    return max(low, min(high, val))
