# grid_helpers.py
"""Helper functions for accessing grid-based data.

These functions provide convenient access to data stored in NumPy arrays,
abstracting away coordinate conversions and aggregations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import numpy as np

from world.terrain import SoilLayer, units_to_meters

if TYPE_CHECKING:
    from main import GameState

def get_grid_elevation(state: "GameState", sx: int, sy: int) -> int:
    """Get absolute elevation of a grid cell in depth units from arrays.

    Elevation = bedrock_base + sum(all layer depths)
    """
    # This is faster than np.sum on a slice for a single cell
    layers_total = (
        state.terrain_layers[0, sx, sy] + state.terrain_layers[1, sx, sy] +
        state.terrain_layers[2, sx, sy] + state.terrain_layers[3, sx, sy] +
        state.terrain_layers[4, sx, sy] + state.terrain_layers[5, sx, sy]
    )
    return state.bedrock_base[sx, sy] + layers_total


def get_total_elevation(state: "GameState", sx: int, sy: int) -> float:
    """Get total elevation at a grid cell in meters.

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total elevation in meters
    """
    return units_to_meters(
        state.bedrock_base[sx, sy] +
        np.sum(state.terrain_layers[:, sx, sy])
    )


def get_exposed_material(state: "GameState", sx: int, sy: int) -> str:
    """Get topmost non-zero material name at grid cell.

    Args:
        state: Game state
        sx, sy: Grid coordinates

    Returns:
        Material name, or "bedrock" if no soil layers
    """
    for layer in reversed([SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                          SoilLayer.SUBSOIL, SoilLayer.REGOLITH]):
        if state.terrain_layers[layer, sx, sy] > 0:
            return state.terrain_materials[layer, sx, sy]
    return "bedrock"


def get_cell_neighborhood_subsurface_water(state: "GameState", sx: int, sy: int) -> int:
    """Get total subsurface water for a grid cell and its 8 neighbors (3×3 area).

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total subsurface water in units across the 3×3 neighborhood
    """
    from config import GRID_WIDTH, GRID_HEIGHT
    total = 0
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            gx, gy = sx + dx, sy + dy
            if 0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT:
                total += int(state.subsurface_water_grid[:, gx, gy].sum())
    return total


def get_grid_subsurface_water(state: "GameState", sx: int, sy: int) -> int:
    """Get total subsurface water at a grid cell (sum of all layers).

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total subsurface water in units
    """
    return int(state.subsurface_water_grid[:, sx, sy].sum())


def get_cell_neighborhood_surface_water(state: "GameState", sx: int, sy: int) -> int:
    """Get total surface water for a grid cell and its 8 neighbors (3×3 area).

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total surface water in units across the 3×3 neighborhood
    """
    from config import GRID_WIDTH, GRID_HEIGHT
    total = 0
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            gx, gy = sx + dx, sy + dy
            if 0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT:
                total += int(state.water_grid[gx, gy])
    return total


def get_cell_neighborhood_total_water(state: "GameState", sx: int, sy: int) -> int:
    """Get total water (surface + subsurface) for a grid cell and its 8 neighbors.

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total water in units across the 3×3 neighborhood
    """
    surface = get_cell_neighborhood_surface_water(state, sx, sy)
    subsurface = get_cell_neighborhood_subsurface_water(state, sx, sy)
    return surface + subsurface


