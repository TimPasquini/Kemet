# render/colors.py
"""Color calculations and utilities for tile rendering."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, cast

from ground import MATERIAL_LIBRARY
from surface_state import compute_surface_appearance
from config import (
    BIOME_COLORS,
    ELEVATION_BRIGHTNESS_MIN,
    ELEVATION_BRIGHTNESS_MAX,
    MATERIAL_BLEND_WEIGHT,
    ORGANICS_BLEND_WEIGHT,
)

if TYPE_CHECKING:
    from main import GameState
    from subgrid import SubSquare

Color = Tuple[int, int, int]


def calculate_elevation_range(state: "GameState") -> Tuple[float, float]:
    """Calculate min/max elevation across all tiles."""
    elevations = [state.tiles[x][y].elevation for x in range(state.width) for y in range(state.height)]
    return (min(elevations), max(elevations)) if elevations else (0, 0)


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


def get_surface_material_color(tile) -> Color | None:
    """Get the display color for the tile's surface material."""
    terrain = tile.terrain
    if terrain.organics_depth > 0:
        props = MATERIAL_LIBRARY.get("humus")
        if props:
            return props.display_color
    props = MATERIAL_LIBRARY.get(terrain.topsoil_material)
    if props:
        return props.display_color
    return None


def color_for_tile(state_tile, tile_type, elevation_range: Tuple[float, float]) -> Color:
    """Calculate the final display color for a tile (legacy, uses tile.kind)."""
    # Water-saturated tiles show as blue
    if state_tile.hydration >= 10.0:
        return 48, 133, 214
    if state_tile.hydration >= 5.0:
        return 92, 180, 238

    # Start with biome base color
    base_color = BIOME_COLORS.get(tile_type.name, (200, 200, 200))

    # Blend with surface material color
    material_color = get_surface_material_color(state_tile)
    if material_color:
        weight = ORGANICS_BLEND_WEIGHT if state_tile.terrain.organics_depth > 0 else MATERIAL_BLEND_WEIGHT
        base_color = blend_colors(base_color, material_color, weight)

    # Apply elevation-based brightness
    min_elev, max_elev = elevation_range
    brightness = elevation_brightness(state_tile.elevation, min_elev, max_elev)
    base_color = apply_brightness(base_color, brightness)

    return base_color


def color_for_subsquare(
    subsquare: "SubSquare",
    subsquare_elevation: float,
    tile,
    elevation_range: Tuple[float, float]
) -> Color:
    """Calculate the display color for a sub-square from computed appearance.

    The appearance is computed from environmental factors (exposed material,
    water state, organics) rather than a stored biome string.

    Args:
        subsquare: The sub-square to render
        subsquare_elevation: Absolute elevation of the sub-square
        tile: Parent tile (for terrain data if no override)
        elevation_range: (min, max) elevation for brightness scaling
    """
    # Compute appearance from environmental factors
    appearance = compute_surface_appearance(subsquare, tile)

    # Start with computed base color
    base_color = appearance.display_color

    # Apply elevation-based brightness
    min_elev, max_elev = elevation_range
    brightness = elevation_brightness(subsquare_elevation, min_elev, max_elev)
    base_color = apply_brightness(base_color, brightness)

    return base_color
