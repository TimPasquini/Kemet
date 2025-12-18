# simulation/subsurface.py
"""Tile-level subsurface water simulation.

Handles underground water movement at tile resolution:
- Vertical seepage between soil layers
- Horizontal subsurface flow based on hydraulic pressure
- Overflow handling when layers exceed capacity
- Upward seepage to surface (distributed to sub-squares)

This runs at lower frequency than surface flow (every N ticks).
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Tuple

from ground import SoilLayer, MATERIAL_LIBRARY
from water import (
    WaterColumn,
    simulate_vertical_seepage,
    calculate_subsurface_flow,
    calculate_overflows,
)
from utils import get_neighbors
from config import (
    RAIN_WELLSPRING_MULTIPLIER,
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)
from mapgen import TILE_TYPES
from simulation.surface import distribute_upward_seepage, get_tile_surface_water

if TYPE_CHECKING:
    from main import GameState
    from mapgen import Tile

Point = Tuple[int, int]


def simulate_subsurface_tick(state: "GameState") -> None:
    """Run one tick of subsurface water simulation using active tile sets.

    Args:
        state: Game state with tiles and active set caches.
    """
    capillary_rises: dict[tuple[int, int], int] = {}
    wellspring_tiles = [(x, y) for x in range(state.width) for y in range(state.height) if state.tiles[x][y].wellspring_output > 0]

    # Process wellsprings separately
    for x, y in wellspring_tiles:
        tile = state.tiles[x][y]
        multiplier = RAIN_WELLSPRING_MULTIPLIER if state.raining else 100
        desired = (tile.wellspring_output * multiplier) // 100
        actual = state.water_pool.wellspring_draw(desired)
        if actual > 0:
            tile.water.add_layer_water(SoilLayer.REGOLITH, actual)
            state.active_water_tiles.add((x, y))

    # Process vertical seepage only on active tiles
    for x, y in list(state.active_water_tiles):
        tile = state.tiles[x][y]
        surface_water = get_tile_surface_water(tile)
        capillary = simulate_vertical_seepage(tile.terrain, tile.water, surface_water)
        if capillary > 0:
            capillary_rises[(x, y)] = capillary
        if tile.water.total_subsurface_water() <= 0:
            state.active_water_tiles.discard((x,y))

    # --- Horizontal Flow ---
    # Create snapshot only for active tiles and their neighbors
    flow_candidate_coords = set(state.active_water_tiles)
    for x, y in state.active_water_tiles:
        for nx, ny in get_neighbors(x, y, state.width, state.height):
            flow_candidate_coords.add((nx, ny))

    if not flow_candidate_coords:
         # Apply capillary rise even if there's no horizontal flow
        for (x, y), amount in capillary_rises.items():
            distribute_upward_seepage(state.tiles[x][y], amount, state.active_water_subsquares, x, y)
        return

    tiles_data = {
        (x, y): (state.tiles[x][y].terrain, state.tiles[x][y].water)
        for x, y in flow_candidate_coords
    }

    subsurface_deltas = calculate_subsurface_flow(tiles_data, state.width, state.height)
    overflow_sub_deltas, overflow_surf_deltas = calculate_overflows(tiles_data, state.width, state.height)

    for key, value in overflow_sub_deltas.items():
        subsurface_deltas[key] = subsurface_deltas.get(key, 0) + value

    # Apply deltas and update active sets
    for ((x, y), layer), amount in subsurface_deltas.items():
        tile = state.tiles[x][y]
        current = tile.water.get_layer_water(layer)
        tile.water.set_layer_water(layer, max(0, current + amount))
        if tile.water.total_subsurface_water() > 0:
            state.active_water_tiles.add((x, y))
        else:
            state.active_water_tiles.discard((x, y))

    for (x, y), amount in overflow_surf_deltas.items():
        if amount > 0:
            distribute_upward_seepage(state.tiles[x][y], amount, state.active_water_subsquares, x, y)

    for (x, y), amount in capillary_rises.items():
        distribute_upward_seepage(state.tiles[x][y], amount, state.active_water_subsquares, x, y)


def apply_tile_evaporation(state: "GameState") -> None:
    """Apply evaporation to active surface water sub-squares.

    This is much faster than iterating the whole grid.

    Args:
        state: Game state with tiles and active_water_subsquares set.
    """
    # Iterate over a copy as the set can be modified
    for sub_x, sub_y in list(state.active_water_subsquares):
        tile_x, tile_y = sub_x // 3, sub_y // 3
        local_x, local_y = sub_x % 3, sub_y % 3
        tile = state.tiles[tile_x][tile_y]
        subsquare = tile.subgrid[local_x][local_y]

        if subsquare.surface_water <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))
            continue

        base_evap = (TILE_TYPES[tile.kind].evap * state.heat) // 100
        if state.atmosphere is not None:
            base_evap = int(base_evap * state.atmosphere.get_evaporation_modifier(tile_x, tile_y))
        if state.tile_has_cistern(tile_x, tile_y):
            base_evap = (base_evap * CISTERN_EVAP_REDUCTION) // 100

        retention = TILE_TYPES[tile.kind].retention
        tile_evap = base_evap - ((retention * base_evap) // 100)

        if tile_evap <= 0:
            continue

        sub_evap = tile_evap
        if subsquare.has_trench:
            sub_evap = (sub_evap * TRENCH_EVAP_REDUCTION) // 100

        evaporated = min(sub_evap, subsquare.surface_water)
        if evaporated > 0:
            subsquare.surface_water -= evaporated
            state.water_pool.evaporate(evaporated)

        if subsquare.surface_water <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))
