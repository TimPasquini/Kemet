# simulation/subsurface.py
"""Surface water evaporation (grid-based).

Note: Subsurface water simulation has been moved to subsurface_vectorized.py.
This module only contains the evaporation function which runs on surface water.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import numpy as np

from world.terrain import BIOME_TYPES
from config import (
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)

if TYPE_CHECKING:
    from main import GameState


def apply_tile_evaporation(state: "GameState") -> None:
    """Apply evaporation to active surface water grid cells (vectorized).

    Uses grid-based atmosphere (humidity_grid, wind_grid) instead of legacy
    AtmosphereLayer regions. Calculates evaporation modifier from humidity
    and wind magnitude at each active cell.

    Args:
        state: Game state with grids and active_water_cells set.
    """
    if len(state.active_water_cells) == 0:
        return

    # Extract active cell coordinates as arrays
    active_coords = list(state.active_water_cells)
    rows = np.array([c[0] for c in active_coords], dtype=np.int32)
    cols = np.array([c[1] for c in active_coords], dtype=np.int32)

    # Get water amounts
    water_amounts = state.water_grid[rows, cols]

    # Filter out cells with no water
    has_water = water_amounts > 0
    if not np.any(has_water):
        return

    rows = rows[has_water]
    cols = cols[has_water]
    water_amounts = water_amounts[has_water]

    # Get biome kinds for each cell (using grid coordinates)
    cell_kinds = np.array([state.get_cell_kind(sx, sy) for sx, sy in zip(rows, cols)])

    # Base evaporation from biome properties
    base_evaps = np.array([
        (BIOME_TYPES[kind].evap * state.heat) // 100
        for kind in cell_kinds
    ], dtype=np.int32)

    # === Atmosphere modifier (NEW: grid-based) ===
    # Check for both new grid-based and legacy atmosphere systems
    if state.humidity_grid is not None and state.wind_grid is not None:
        # NEW: Grid-based atmosphere
        # Get humidity at each cell
        humidity = state.humidity_grid[rows, cols]

        # Get wind magnitude at each cell
        wind_x = state.wind_grid[rows, cols, 0]
        wind_y = state.wind_grid[rows, cols, 1]
        wind_magnitude = np.sqrt(wind_x**2 + wind_y**2)

        # Calculate evaporation modifier (matching legacy formula)
        # humidity_mod = 1.5 - humidity (high humidity = low evap)
        # wind_mod = 1.0 + wind_speed * 0.3
        humidity_mod = 1.5 - humidity
        wind_mod = 1.0 + wind_magnitude * 0.3
        atmos_modifier = humidity_mod * wind_mod

        # Apply atmosphere modifier
        base_evaps = (base_evaps * atmos_modifier).astype(np.int32)

    # Cistern reduction (vectorized check using grid coordinates)
    has_cistern = np.array([
        state.cell_has_cistern(sx, sy) for sx, sy in zip(rows, cols)
    ], dtype=bool)
    base_evaps = np.where(has_cistern,
                          (base_evaps * CISTERN_EVAP_REDUCTION) // 100,
                          base_evaps)

    # Retention reduction
    retentions = np.array([BIOME_TYPES[kind].retention for kind in cell_kinds])
    tile_evaps = base_evaps - ((retentions * base_evaps) // 100)

    # Filter non-positive evaporation
    evaporates = tile_evaps > 0
    if not np.any(evaporates):
        return

    rows = rows[evaporates]
    cols = cols[evaporates]
    tile_evaps = tile_evaps[evaporates]
    water_amounts = water_amounts[evaporates]

    # Trench reduction (vectorized)
    has_trench = state.trench_grid[rows, cols] > 0
    sub_evaps = np.where(has_trench,
                         (tile_evaps * TRENCH_EVAP_REDUCTION) // 100,
                         tile_evaps)

    # Calculate actual evaporation (capped by available water)
    evaporated = np.minimum(sub_evaps, water_amounts)

    # Apply evaporation (vectorized)
    state.water_grid[rows, cols] -= evaporated
    state.water_pool.evaporate(int(np.sum(evaporated)))

    # Remove cells with no water from active set
    final_water = state.water_grid[rows, cols]
    empty_cells = final_water <= 0
    if np.any(empty_cells):
        empty_coords = set(zip(rows[empty_cells], cols[empty_cells]))
        state.active_water_cells -= empty_coords
