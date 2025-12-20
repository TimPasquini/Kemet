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

from ground import SoilLayer, MATERIAL_LIBRARY, TerrainColumn, layers_can_connect, TILE_TYPES
from water import WaterColumn
from utils import get_neighbors
from config import (
    RAIN_WELLSPRING_MULTIPLIER,
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)
from simulation.config import (
    SUBSURFACE_FLOW_RATE,
    VERTICAL_SEEPAGE_RATE,
    CAPILLARY_RISE_RATE,
    SUBSURFACE_FLOW_THRESHOLD,
)
from simulation.surface import distribute_upward_seepage, get_tile_surface_water

if TYPE_CHECKING:
    from main import GameState
    from mapgen import Tile

Point = Tuple[int, int]


def _calculate_seep(
        source_water: int,
        permeability: int,
        rate_pct: int,
        capacity: int,
) -> int:
    """Helper to calculate how much water can seep."""
    if source_water <= 0 or capacity <= 0:
        return 0

    seep_potential = (source_water * permeability * rate_pct) // 10000
    return min(seep_potential, capacity, source_water)


def _calculate_hydraulic_head(terrain: TerrainColumn, water: WaterColumn, layer: SoilLayer) -> int:
    """Calculate hydraulic head (pressure) for a layer."""
    bottom, top = terrain.get_layer_elevation_range(layer)

    water_in_layer = water.get_layer_water(layer)
    max_storage = terrain.get_max_water_storage(layer)

    if max_storage > 0 and water_in_layer > 0:
        # Water fills from bottom up
        layer_depth = top - bottom
        # Allow head to calculate for over-capacity water
        water_height = (water_in_layer * layer_depth) // max_storage
        return bottom + water_height

    return bottom  # Empty layer has minimum head


def simulate_vertical_seepage(terrain: TerrainColumn, water: WaterColumn, surface_water_total: int = 0) -> int:
    """
    Simulate water seeping vertically through soil layers, one layer at a time.
    This version prevents the "waterfall" bug.

    Args:
        terrain: Terrain column for layer properties
        water: Water column for subsurface water storage
        surface_water_total: Total surface water on this tile's sub-squares (for capillary check)

    Returns:
        Amount of water to distribute to surface via capillary rise
    """
    # --- Downward Seepage between soil layers ---
    # Note: Surface-to-soil seepage is handled per-sub-square in simulation/surface.py

    # 1. Seep between adjacent soil layers (one step at a time)
    # Create a list of transfers to apply atomically, preventing the waterfall effect.
    transfers: Dict[SoilLayer, int] = defaultdict(int)
    soil_layers = list(reversed(SoilLayer))  # [Organics, Topsoil, ..., Bedrock]
    for i in range(len(soil_layers) - 1):
        from_layer, to_layer = soil_layers[i], soil_layers[i + 1]
        if to_layer == SoilLayer.BEDROCK: continue

        source_water = water.get_layer_water(from_layer)
        if source_water <= 0: continue

        available_capacity = terrain.get_max_water_storage(to_layer) - water.get_layer_water(to_layer)
        if available_capacity <= 0: continue

        props = MATERIAL_LIBRARY.get(terrain.get_layer_material(from_layer))
        if props:
            seep_amount = _calculate_seep(
                source_water,
                props.permeability_vertical,
                VERTICAL_SEEPAGE_RATE,
                available_capacity
            )
            if seep_amount > 0:
                transfers[from_layer] -= seep_amount
                transfers[to_layer] += seep_amount

    # Apply all the calculated transfers at once
    for layer, delta in transfers.items():
        water.add_layer_water(layer, delta)

    # 2. Bedrock pressure: push water up from oversaturated Regolith
    regolith_capacity = terrain.get_max_water_storage(SoilLayer.REGOLITH)
    regolith_water = water.get_layer_water(SoilLayer.REGOLITH)
    if regolith_water > regolith_capacity:
        excess = regolith_water - regolith_capacity
        water.set_layer_water(SoilLayer.REGOLITH, regolith_capacity)
        water.add_layer_water(SoilLayer.SUBSOIL, excess)  # Push up to subsoil

    # --- Upward Movement (Capillary Action) ---
    # Only rise if surface is relatively dry (less than 1cm equivalent)
    capillary_rise = 0
    if surface_water_total < 10:
        # Find topmost layer with water
        for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION]:
            if terrain.get_layer_depth(layer) > 0 and water.get_layer_water(layer) > 0:
                material = terrain.get_layer_material(layer)
                props = MATERIAL_LIBRARY.get(material)
                if props:
                    source_water = water.get_layer_water(layer)
                    rise_amount = _calculate_seep(
                        source_water,
                        props.permeability_vertical,
                        CAPILLARY_RISE_RATE,
                        source_water  # Effectively unlimited capacity
                    )
                    if rise_amount > 0:
                        water.remove_layer_water(layer, rise_amount)
                        capillary_rise = rise_amount
                break  # Only rise from the single topmost wet layer

    return capillary_rise


def calculate_subsurface_flow(
        tiles_data: Dict[Point, Tuple[TerrainColumn, WaterColumn]],
        width: int,
        height: int,
) -> Dict[Tuple[Point, SoilLayer], int]:
    """
    Calculate subsurface water flow based on hydraulic pressure.
    Now uses a dictionary of active tiles for performance.
    """
    deltas: Dict[Tuple[Point, SoilLayer], int] = defaultdict(int)

    for layer in [SoilLayer.REGOLITH, SoilLayer.SUBSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.TOPSOIL, SoilLayer.ORGANICS]:

        for (x, y), (terrain, water) in tiles_data.items():
            if terrain.get_layer_depth(layer) == 0 or water.get_layer_water(layer) == 0:
                continue

            material = terrain.get_layer_material(layer)
            props = MATERIAL_LIBRARY.get(material)
            if not props:
                continue

            my_head = _calculate_hydraulic_head(terrain, water, layer)
            flow_targets = []
            total_diff = 0

            for nx, ny in get_neighbors(x, y, width, height):
                neighbor_data = tiles_data.get((nx, ny))
                if not neighbor_data:
                    continue
                n_terrain, n_water = neighbor_data

                if n_terrain.get_layer_depth(layer) == 0:
                    continue
                if not layers_can_connect(terrain, layer, n_terrain, layer):
                    continue

                n_head = _calculate_hydraulic_head(n_terrain, n_water, layer)
                diff = my_head - n_head

                if diff > SUBSURFACE_FLOW_THRESHOLD:
                    flow_targets.append(((nx, ny), diff))
                    total_diff += diff

            if not flow_targets:
                continue

            water_available = water.get_layer_water(layer)
            flow_pct = (props.permeability_horizontal * SUBSURFACE_FLOW_RATE) // 100
            transferable = (water_available * flow_pct) // 100

            total_transferred = 0
            for (nx, ny), diff in flow_targets:
                portion = (transferable * diff) // total_diff if total_diff > 0 else 0
                if portion > 0:
                    deltas[((nx, ny), layer)] += portion
                    total_transferred += portion

            if total_transferred > 0:
                deltas[((x, y), layer)] -= total_transferred

    return deltas


def calculate_overflows(
        tiles_data: Dict[Point, Tuple[TerrainColumn, WaterColumn]],
        width: int,
        height: int,
) -> Tuple[Dict[Tuple[Point, SoilLayer], int], Dict[Point, int]]:
    """
    Calculates distribution of water in layers that are over capacity.
    Now uses a dictionary of active tiles for performance.
    """
    sub_deltas: Dict[Tuple[Point, SoilLayer], int] = defaultdict(int)
    surf_deltas: Dict[Point, int] = defaultdict(int)

    for layer in reversed(SoilLayer):
        if layer == SoilLayer.BEDROCK: continue

        for (x, y), (terrain, water) in tiles_data.items():
            max_storage = terrain.get_max_water_storage(layer)
            current_water = water.get_layer_water(layer)

            if current_water <= max_storage:
                continue

            overflow_amount = current_water - max_storage
            my_head = _calculate_hydraulic_head(terrain, water, layer)

            flow_targets = []
            total_diff = 0
            for nx, ny in get_neighbors(x, y, width, height):
                neighbor_data = tiles_data.get((nx, ny))
                if not neighbor_data:
                    continue
                n_terrain, n_water = neighbor_data

                if n_terrain.get_layer_depth(layer) == 0: continue
                if not layers_can_connect(terrain, layer, n_terrain, layer): continue

                n_head = _calculate_hydraulic_head(n_terrain, n_water, layer)
                diff = my_head - n_head
                if diff > 0:
                    flow_targets.append(((nx, ny), diff))
                    total_diff += diff

            if not flow_targets:
                sub_deltas[((x, y), layer)] -= overflow_amount
                surf_deltas[(x, y)] += overflow_amount
                continue

            total_transferred = 0
            for (nx, ny), diff in flow_targets:
                portion = (overflow_amount * diff) // total_diff if total_diff > 0 else 0
                if portion > 0:
                    sub_deltas[((nx, ny), layer)] += portion
                    total_transferred += portion

            if total_transferred > 0:
                sub_deltas[((x, y), layer)] -= total_transferred

    return sub_deltas, surf_deltas


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
