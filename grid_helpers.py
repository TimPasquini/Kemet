# grid_helpers.py
"""Helper functions for accessing grid-based data.

These functions provide convenient access to data stored in NumPy arrays,
abstracting away coordinate conversions and aggregations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import numpy as np

from ground import SoilLayer, units_to_meters
from config import SUBGRID_SIZE

if TYPE_CHECKING:
    from main import GameState

def get_grid_elevation(state: "GameState", sx: int, sy: int) -> int:
    """Get absolute elevation of a grid cell in depth units from arrays.

    Elevation = bedrock_base + sum(all layer depths) + elevation_offset
    """
    # This is faster than np.sum on a slice for a single cell
    layers_total = (
        state.terrain_layers[0, sx, sy] + state.terrain_layers[1, sx, sy] +
        state.terrain_layers[2, sx, sy] + state.terrain_layers[3, sx, sy] +
        state.terrain_layers[4, sx, sy] + state.terrain_layers[5, sx, sy]
    )
    return state.bedrock_base[sx, sy] + layers_total + state.elevation_offset_grid[sx, sy]


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
        np.sum(state.terrain_layers[:, sx, sy]) +
        state.elevation_offset_grid[sx, sy]
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


def get_tile_subsurface_water(state: "GameState", tx: int, ty: int) -> int:
    """Get total subsurface water for a tile (sum of all 9 grid cells, all layers).

    Args:
        state: Game state
        tx, ty: Tile coordinates (0-59, 0-44)

    Returns:
        Total subsurface water in units
    """
    gx_start = tx * SUBGRID_SIZE
    gy_start = ty * SUBGRID_SIZE
    return int(state.subsurface_water_grid[
        :,  # All layers
        gx_start:gx_start + SUBGRID_SIZE,
        gy_start:gy_start + SUBGRID_SIZE
    ].sum())


def get_grid_subsurface_water(state: "GameState", sx: int, sy: int) -> int:
    """Get total subsurface water at a grid cell (sum of all layers).

    Args:
        state: Game state
        sx, sy: Grid coordinates (0-179, 0-134)

    Returns:
        Total subsurface water in units
    """
    return int(state.subsurface_water_grid[:, sx, sy].sum())


def get_tile_total_water(state: "GameState", tx: int, ty: int) -> int:
    """Get total water for a tile (surface + subsurface).

    Args:
        state: Game state
        tx, ty: Tile coordinates (0-59, 0-44)

    Returns:
        Total water in units
    """
    # Since get_tile_surface_water just needs tile coords, we can refactor this later
    # For now, get surface water directly
    gx_start = tx * SUBGRID_SIZE
    gy_start = ty * SUBGRID_SIZE
    surface = int(state.water_grid[
        gx_start:gx_start + SUBGRID_SIZE,
        gy_start:gy_start + SUBGRID_SIZE
    ].sum())
    subsurface = get_tile_subsurface_water(state, tx, ty)
    return surface + subsurface


def get_tile_average_moisture(state: "GameState", tx: int, ty: int) -> float:
    """Get average moisture for a tile from moisture grid.

    Args:
        state: Game state
        tx, ty: Tile coordinates (0-59, 0-44)

    Returns:
        Average moisture value
    """
    if state.moisture_grid is None:
        return 0.0

    gx_start = tx * SUBGRID_SIZE
    gy_start = ty * SUBGRID_SIZE
    tile_moisture = state.moisture_grid[
        gx_start:gx_start + SUBGRID_SIZE,
        gy_start:gy_start + SUBGRID_SIZE
    ]
    return float(tile_moisture.mean())
