# render/colors.py
"""Color calculations and utilities for grid-based rendering.

Provides utilities for:
- Elevation-based brightness scaling
- Color blending
- Elevation range calculation from grid data
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, cast

from render.config import (
    ELEVATION_BRIGHTNESS_MIN,
    ELEVATION_BRIGHTNESS_MAX,
)

if TYPE_CHECKING:
    from main import GameState

Color = Tuple[int, int, int]


def calculate_elevation_range(state: "GameState") -> Tuple[float, float]:
    """Calculate min/max elevation across all grid cells (array-based)."""
    import numpy as np
    from core.config import GRID_WIDTH, GRID_HEIGHT

    # Calculate elevation for all cells: bedrock_base + sum(layers)
    elevations = state.bedrock_base + np.sum(state.terrain_layers, axis=0)

    min_elev = int(np.min(elevations))
    max_elev = int(np.max(elevations))

    return (min_elev, max_elev)


def elevation_brightness(elevation: float, min_elev: float, max_elev: float) -> float:
    """Calculate brightness multiplier based on elevation."""
    if max_elev == min_elev:
        return 1.0
    normalized = (elevation - min_elev) / (max_elev - min_elev)
    return ELEVATION_BRIGHTNESS_MIN + (normalized * (ELEVATION_BRIGHTNESS_MAX - ELEVATION_BRIGHTNESS_MIN))


def apply_brightness(color: Color, brightness: float) -> Color:
    """Apply brightness multiplier to a color."""
    return cast(Color, tuple(max(0, min(255, int(c * brightness))) for c in color))


def blend_colors(color1: Color, color2: Color, weight: float = 0.5) -> Color:
    """Blend two colors with given weight (0 = all color1, 1 = all color2)."""
    return cast(Color, tuple(int(c1 * (1 - weight) + c2 * weight) for c1, c2 in zip(color1, color2)))
