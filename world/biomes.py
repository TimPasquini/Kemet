# world/biomes.py
"""
Biome calculation and recalculation system for Kemet.

Handles determining biome types based on terrain properties like elevation,
moisture, soil composition, and neighbor influence.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple, TYPE_CHECKING

import numpy as np
from config import GRID_WIDTH, GRID_HEIGHT
from world.terrain import SoilLayer
from utils import get_neighbors

if TYPE_CHECKING:
    from main import GameState

Point = Tuple[int, int]


def calculate_biome(
    state: "GameState",
    sx: int,
    sy: int,
    neighbor_positions: List[Point],
    elevation_percentile: float,
    avg_moisture: float
) -> str:
    """
    Determine the biome type for a grid cell based on its properties.

    Args:
        state: GameState with terrain grids
        sx: Grid cell x coordinate
        sy: Grid cell y coordinate
        neighbor_positions: List of (sx, sy) tuples for adjacent grid cells
        elevation_percentile: 0.0-1.0 ranking of elevation (0=lowest, 1=highest)
        avg_moisture: Average moisture level for this cell

    Returns:
        Biome key string (e.g., "dune", "wadi", "rock")
    """
    # Calculate soil depth from terrain layers
    soil_depth = (
        state.terrain_layers[SoilLayer.TOPSOIL, sx, sy] +
        state.terrain_layers[SoilLayer.SUBSOIL, sx, sy]
    )

    topsoil_material = state.terrain_materials[SoilLayer.TOPSOIL, sx, sy]
    organics_depth = state.terrain_layers[SoilLayer.ORGANICS, sx, sy]

    # High elevation with thin soil -> rock
    if elevation_percentile > 0.75 and soil_depth < 5:
        return "rock"

    # Low elevation with moisture -> wadi
    if elevation_percentile < 0.25 and avg_moisture > 50:
        return "wadi"

    # Sandy and dry -> dune
    if topsoil_material == "sand" and avg_moisture < 20:
        return "dune"

    # Low elevation, dry, no organics -> salt flat
    if elevation_percentile < 0.4 and avg_moisture < 15 and organics_depth == 0:
        return "salt"

    # Follow neighbors if strong consensus
    if neighbor_positions:
        neighbor_biomes = [state.get_cell_kind(nx, ny) for nx, ny in neighbor_positions]
        biome_counts = Counter(neighbor_biomes)
        most_common_list = biome_counts.most_common(1)
        if most_common_list:
            most_common, count = most_common_list[0]
            if count >= 3 and most_common in ("dune", "flat", "wadi"):
                return most_common

    return "flat"


def calculate_elevation_percentiles(
    elevation_grid: np.ndarray
) -> np.ndarray:
    """
    Calculate elevation percentile for each grid cell using vectorized operations.

    Args:
        elevation_grid: Grid of elevation values (GRID_WIDTH × GRID_HEIGHT)

    Returns: Array of same shape with percentile values (0.0 = lowest, 1.0 = highest)
    """
    # Flatten the elevation grid while preserving shape info
    flat_elev = elevation_grid.flatten()

    # Use argsort to get ranking (indices that would sort the array)
    # Then argsort again to get the rank of each element
    sorted_indices = np.argsort(flat_elev)
    ranks = np.empty_like(sorted_indices)
    ranks[sorted_indices] = np.arange(len(flat_elev))

    # Convert ranks to percentiles (0.0 to 1.0)
    total = len(flat_elev)
    percentiles_flat = ranks / max(1, total - 1)

    # Reshape back to grid shape
    return percentiles_flat.reshape(elevation_grid.shape).astype(np.float32)


def recalculate_biomes(
    state: "GameState", moisture_grid: np.ndarray
) -> List[str]:
    """
    Recalculate biomes for all grid cells based on current conditions.

    Called daily to allow landscape evolution based on moisture, etc.

    Args:
        state: GameState with terrain grids and kind_grid
        moisture_grid: (GRID_WIDTH, GRID_HEIGHT) array of average moisture values

    Returns:
        List of messages to display to player
    """
    messages: List[str] = []
    # Vectorized elevation percentile calculation
    percentiles = calculate_elevation_percentiles(state.elevation_grid)
    changes = 0

    # Note: Full vectorization of biome calculation is complex due to neighbor consensus logic
    # This optimization focuses on the percentile calculation which was the main bottleneck
    for sy in range(GRID_HEIGHT):
        for sx in range(GRID_WIDTH):
            neighbor_positions = get_neighbors(sx, sy, GRID_WIDTH, GRID_HEIGHT)
            elev_pct = percentiles[sx, sy]  # Now array access instead of dict lookup
            avg_moisture = moisture_grid[sx, sy]
            new_biome = calculate_biome(state, sx, sy, neighbor_positions, elev_pct, avg_moisture)

            old_biome = state.kind_grid[sx, sy]

            if new_biome != old_biome:
                state.kind_grid[sx, sy] = new_biome
                changes += 1

    if changes > 0:
        messages.append(f"Landscape shifted: {changes} cells changed biome.")

    return messages
