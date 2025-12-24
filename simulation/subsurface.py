# simulation/subsurface.py
"""Surface water evaporation (grid-based).

Note: Subsurface water simulation has been moved to subsurface_vectorized.py.
This module only contains the evaporation function which runs on surface water.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ground import TILE_TYPES
from config import (
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)

if TYPE_CHECKING:
    from main import GameState


def apply_tile_evaporation(state: "GameState") -> None:
    """Apply evaporation to active surface water grid cells.

    This is much faster than iterating the whole grid.

    NOTE: This function uses the legacy object-oriented atmosphere system
    (AtmosphereLayer/AtmosphereRegion) which will be replaced with grid-based
    atmosphere in Phase 3. After atmosphere vectorization, this will need
    to be updated to use humidity_grid instead of state.atmosphere.get_evaporation_modifier().

    Args:
        state: Game state with grids and active_water_subsquares set.
    """
    # Iterate over a copy as the set can be modified
    for sub_x, sub_y in list(state.active_water_subsquares):
        tile_x, tile_y = sub_x // 3, sub_y // 3
        water_amt = state.water_grid[sub_x, sub_y]

        if water_amt <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))
            continue

        tile_kind = state.get_tile_kind(tile_x, tile_y)
        base_evap = (TILE_TYPES[tile_kind].evap * state.heat) // 100
        if state.atmosphere is not None:
            base_evap = int(base_evap * state.atmosphere.get_evaporation_modifier(tile_x, tile_y))
        if state.tile_has_cistern(tile_x, tile_y):
            base_evap = (base_evap * CISTERN_EVAP_REDUCTION) // 100

        retention = TILE_TYPES[tile_kind].retention
        tile_evap = base_evap - ((retention * base_evap) // 100)

        if tile_evap <= 0:
            continue

        sub_evap = tile_evap
        if state.trench_grid[sub_x, sub_y]:
            sub_evap = (sub_evap * TRENCH_EVAP_REDUCTION) // 100

        evaporated = min(sub_evap, water_amt)
        if evaporated > 0:
            state.water_grid[sub_x, sub_y] -= evaporated
            state.water_pool.evaporate(evaporated)

        if state.water_grid[sub_x, sub_y] <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))
