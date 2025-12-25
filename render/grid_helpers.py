# render/grid_helpers.py
"""Helper functions for grid-based rendering (array-based)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
import numpy as np

from world.terrain import SoilLayer, units_to_meters

if TYPE_CHECKING:
    from main import GameState


def get_grid_elevation(state: "GameState", sx: int, sy: int) -> int:
    """Get absolute elevation of a grid cell in depth units.

    Elevation = bedrock_base + sum(all layer depths)
    """
    bedrock = state.bedrock_base[sx, sy]
    layers_total = np.sum(state.terrain_layers[:, sx, sy])
    return bedrock + layers_total


def get_tile_elevation_range(state: "GameState", tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Get min and max elevation for a tile's 3x3 grid region."""
    sx_start = tile_x * 3
    sy_start = tile_y * 3
    sx_end = sx_start + 3
    sy_end = sy_start + 3

    # Calculate elevations for all 9 cells
    elevations = []
    for sx in range(sx_start, sx_end):
        for sy in range(sy_start, sy_end):
            elevations.append(get_grid_elevation(state, sx, sy))

    return min(elevations), max(elevations)


def get_exposed_material(state: "GameState", sx: int, sy: int) -> str:
    """Get the material name of the exposed (topmost) layer at a grid cell."""
    # Find topmost non-zero layer
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            return state.terrain_materials[layer, sx, sy]
    return state.terrain_materials[SoilLayer.BEDROCK, sx, sy]  # Bedrock exposed


def calculate_brightness_from_elevation(elevation: int, elevation_range: Tuple[float, float]) -> float:
    """Calculate brightness factor (0.0-1.0) based on elevation within range."""
    min_elev, max_elev = elevation_range
    if max_elev <= min_elev:
        return 0.5  # Flat map, use neutral brightness

    # Normalize elevation to 0-1 range
    normalized = (elevation - min_elev) / (max_elev - min_elev)
    # Map to brightness range 0.3-1.0 (avoid pure black)
    return 0.3 + (normalized * 0.7)


# Appearance types for materials (from surface_state.py)
APPEARANCE_TYPES = {
    "bedrock": (80, 80, 80),
    "rock": (120, 120, 110),
    "gravel": (160, 160, 150),
    "sand": (204, 174, 120),
    "dirt": (150, 120, 90),
    "clay": (120, 100, 80),
    "silt": (140, 110, 85),
    "humus": (60, 50, 40),
}
DEFAULT_COLOR = (150, 120, 90)


def get_grid_cell_color(state: "GameState", sx: int, sy: int, elevation_range: Tuple[float, float]) -> Tuple[int, int, int]:
    """Calculate display color for a grid cell from array data only.

    Args:
        state: Game state with grids
        sx, sy: Grid cell coordinates
        elevation_range: (min, max) elevation for brightness scaling

    Returns:
        RGB color tuple
    """
    # Get exposed material
    material = get_exposed_material(state, sx, sy)

    # Get base color from material
    base_color = APPEARANCE_TYPES.get(material, DEFAULT_COLOR)

    # Apply water tint if present
    surface_water = state.water_grid[sx, sy]
    if surface_water > 0:
        water_color = (60, 120, 180)
        if surface_water > 50:
            tint = 0.4
        elif surface_water > 20:
            tint = 0.25
        elif surface_water > 5:
            tint = 0.1
        else:
            tint = 0.0

        if tint > 0:
            r = int(base_color[0] * (1 - tint) + water_color[0] * tint)
            g = int(base_color[1] * (1 - tint) + water_color[1] * tint)
            b = int(base_color[2] * (1 - tint) + water_color[2] * tint)
            base_color = (r, g, b)

    # Apply elevation-based brightness
    elevation = get_grid_elevation(state, sx, sy)
    brightness = calculate_brightness_from_elevation(elevation, elevation_range)

    final_color = (
        max(0, min(255, int(base_color[0] * brightness))),
        max(0, min(255, int(base_color[1] * brightness))),
        max(0, min(255, int(base_color[2] * brightness))),
    )

    return final_color
