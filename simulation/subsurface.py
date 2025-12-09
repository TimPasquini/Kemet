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
    """Run one tick of subsurface water simulation.

    This handles:
    1. Wellspring water injection
    2. Vertical seepage through soil layers
    3. Horizontal subsurface flow
    4. Overflow to surface (distributed to sub-squares)

    Args:
        state: Game state with tiles and structures
    """
    # 1. Add water from wellsprings and simulate vertical seepage
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]

            # Wellspring output
            if tile.wellspring_output > 0:
                multiplier = RAIN_WELLSPRING_MULTIPLIER if state.raining else 100
                gain = (tile.wellspring_output * multiplier) // 100
                tile.water.add_layer_water(SoilLayer.REGOLITH, gain)

            # Vertical seepage within the tile
            simulate_vertical_seepage(tile.terrain, tile.water)

    # 2. Create snapshot for horizontal flow calculations
    tiles_data = [
        [(state.tiles[x][y].terrain, state.tiles[x][y].water) for y in range(state.height)]
        for x in range(state.width)
    ]

    # 3. Calculate horizontal subsurface flows
    subsurface_deltas = calculate_subsurface_flow(tiles_data, state.width, state.height)

    # 4. Calculate overflow (water pushed to surface from saturated layers)
    overflow_sub_deltas, overflow_surf_deltas = calculate_overflows(
        tiles_data, state.width, state.height
    )

    # Combine subsurface deltas
    for key, value in overflow_sub_deltas.items():
        subsurface_deltas[key] = subsurface_deltas.get(key, 0) + value

    # 5. Apply subsurface flows
    for ((x, y), layer), amount in subsurface_deltas.items():
        tile = state.tiles[x][y]
        current = tile.water.get_layer_water(layer)
        tile.water.set_layer_water(layer, max(0, current + amount))

    # 6. Apply overflow to surface (distribute to sub-squares)
    for (x, y), amount in overflow_surf_deltas.items():
        if amount > 0:
            distribute_upward_seepage(state.tiles[x][y], amount)


def apply_tile_evaporation(state: "GameState") -> None:
    """Apply evaporation to surface water on sub-squares.

    Evaporation is calculated at tile level but applied to sub-squares
    proportionally based on their current water content.

    Args:
        state: Game state with tiles and structures
    """
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]

            # Calculate tile-level evaporation rate
            base_evap = (TILE_TYPES[tile.kind].evap * state.heat) // 100

            # Modifiers
            if tile.surface.has_trench:
                base_evap = (base_evap * TRENCH_EVAP_REDUCTION) // 100

            if (x, y) in state.structures:
                if state.structures[(x, y)].kind == "cistern":
                    base_evap = (base_evap * CISTERN_EVAP_REDUCTION) // 100

            # Apply retention
            retention = TILE_TYPES[tile.kind].retention
            net_evap = base_evap - ((retention * base_evap) // 100)

            if net_evap <= 0:
                continue

            # Get total surface water in tile's sub-squares
            total_water = get_tile_surface_water(tile)
            if total_water <= 0:
                continue

            # Distribute evaporation proportionally across sub-squares
            remaining_evap = min(net_evap, total_water)

            for row in tile.subgrid:
                for subsquare in row:
                    if subsquare.surface_water > 0 and remaining_evap > 0:
                        # Proportion of tile's water in this sub-square
                        proportion = subsquare.surface_water / total_water
                        sub_evap = int(remaining_evap * proportion)
                        sub_evap = min(sub_evap, subsquare.surface_water)
                        subsquare.surface_water -= sub_evap
