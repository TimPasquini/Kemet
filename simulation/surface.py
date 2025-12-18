# simulation/surface.py
"""Sub-grid surface water flow simulation.

Water flows between sub-squares based on elevation differences.
Flow crosses tile boundaries seamlessly - sub-squares are independent units.

Key concepts:
- Each sub-square has its own surface_water amount
- Flow is 8-directional (cardinal + diagonal)
- Elevation = tile base elevation + sub-square elevation_offset
- Water flows from high to low, distributed proportionally
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Set

from config import SUBGRID_SIZE, SURFACE_FLOW_RATE, SURFACE_FLOW_THRESHOLD, SURFACE_SEEPAGE_RATE
from subgrid import NEIGHBORS_8, get_subsquare_index, get_subsquare_terrain, tile_to_subgrid

if TYPE_CHECKING:
    from main import GameState
    from mapgen import Tile
    from world_state import GlobalWaterPool

Point = Tuple[int, int]


def get_subsquare_elevation(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get absolute elevation of a sub-square in depth units."""
    # Tile's terrain surface elevation (in depth units) + sub-square offset
    base_elev = tile.terrain.get_surface_elevation()
    # Convert offset from meters to depth units (1 unit = 0.1m = 100mm)
    offset_units = int(tile.subgrid[local_x][local_y].elevation_offset * 10)
    return base_elev + offset_units


def get_subsquare_water_height(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get water surface height (elevation + water depth) for a sub-square."""
    elev = get_subsquare_elevation(tile, local_x, local_y)
    water = tile.subgrid[local_x][local_y].surface_water
    return elev + water


def simulate_surface_flow(state: "GameState") -> int:
    """Simulate one tick of surface water flow using an active set for performance.

    Water flows from each sub-square in the active set to lower neighbors.
    This avoids iterating over the entire grid every tick.

    Args:
        state: The main game state, containing tiles and active_water_subsquares.

    Returns:
        Total edge runoff amount (for tracking).
    """
    tiles = state.tiles
    width = state.width
    height = state.height
    water_pool = state.water_pool
    sub_width = width * SUBGRID_SIZE
    sub_height = height * SUBGRID_SIZE

    deltas: Dict[Point, int] = defaultdict(int)
    edge_runoff_total = 0
    EDGE_TARGET = (-1, -1)

    # Iterate over a copy of the active set, as it may be modified during the loop
    for sub_x, sub_y in list(state.active_water_subsquares):
        tile_x, tile_y = sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE
        local_x, local_y = sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE
        tile = tiles[tile_x][tile_y]
        subsquare = tile.subgrid[local_x][local_y]

        if subsquare.surface_water <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))
            continue

        my_height = get_subsquare_water_height(tile, local_x, local_y)
        flow_targets: List[Tuple[Point, float]] = []
        total_diff = 0.0

        for dx, dy in NEIGHBORS_8:
            n_sub_x, n_sub_y = sub_x + dx, sub_y + dy

            if not (0 <= n_sub_x < sub_width and 0 <= n_sub_y < sub_height):
                if water_pool is not None:
                    edge_diff = my_height + 100
                    flow_targets.append((EDGE_TARGET, edge_diff))
                    total_diff += edge_diff
                continue

            n_tile_x, n_tile_y = n_sub_x // SUBGRID_SIZE, n_sub_y // SUBGRID_SIZE
            n_local_x, n_local_y = n_sub_x % SUBGRID_SIZE, n_sub_y % SUBGRID_SIZE
            n_tile = tiles[n_tile_x][n_tile_y]
            n_height = get_subsquare_water_height(n_tile, n_local_x, n_local_y)

            diff = my_height - n_height
            if diff > SURFACE_FLOW_THRESHOLD:
                flow_targets.append(((n_sub_x, n_sub_y), diff))
                total_diff += diff

        if not flow_targets:
            continue

        transferable = (subsquare.surface_water * SURFACE_FLOW_RATE) // 100
        if transferable <= 0:
            continue

        total_transferred = 0
        for target, diff in flow_targets:
            portion = int((transferable * diff) / total_diff) if total_diff > 0 else 0
            if portion > 0:
                if target == EDGE_TARGET:
                    edge_runoff_total += portion
                else:
                    deltas[target] += portion
                    state.active_water_subsquares.add(target)  # Activate neighbor
                total_transferred += portion

        if total_transferred > 0:
            deltas[(sub_x, sub_y)] -= total_transferred
            subsquare.water_passage += total_transferred

    if not deltas:
        if water_pool is not None and edge_runoff_total > 0:
            water_pool.edge_runoff(edge_runoff_total)
        return edge_runoff_total

    for (sub_x, sub_y), delta in deltas.items():
        tile_x, tile_y = sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE
        local_x, local_y = sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE
        subsquare = tiles[tile_x][tile_y].subgrid[local_x][local_y]
        subsquare.surface_water = max(0, subsquare.surface_water + delta)

        if delta > 0:
            subsquare.water_passage += delta
        subsquare.check_water_threshold()

        if subsquare.surface_water <= 0:
            state.active_water_subsquares.discard((sub_x, sub_y))

    if water_pool is not None and edge_runoff_total > 0:
        water_pool.edge_runoff(edge_runoff_total)

    return edge_runoff_total


def simulate_surface_seepage(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
) -> None:
    """Simulate surface water seeping into the topmost soil layer.

    Water on each sub-square seeps down into the tile's soil based on
    the permeability of the exposed material.

    Args:
        tiles: 2D list of tiles [x][y]
        width: Map width in tiles
        height: Map height in tiles
    """
    from ground import MATERIAL_LIBRARY, SoilLayer

    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]

            # Get the topmost soil layer for this tile
            exposed_layer = tile.terrain.get_exposed_layer()
            if exposed_layer == SoilLayer.BEDROCK:
                continue  # Can't seep into bedrock

            material = tile.terrain.get_layer_material(exposed_layer)
            props = MATERIAL_LIBRARY.get(material)
            if not props or props.permeability_vertical <= 0:
                continue

            # Calculate capacity remaining in the topmost layer
            max_storage = tile.terrain.get_max_water_storage(exposed_layer)
            current_water = tile.water.get_layer_water(exposed_layer)
            available_capacity = max_storage - current_water

            if available_capacity <= 0:
                continue  # Layer is saturated

            # Process each sub-square
            for row in tile.subgrid:
                for subsquare in row:
                    if subsquare.surface_water <= 0:
                        continue

                    # Calculate seepage amount based on permeability
                    seep_rate = (SURFACE_SEEPAGE_RATE * props.permeability_vertical) // 100
                    seep_amount = (subsquare.surface_water * seep_rate) // 100

                    # Cap at available capacity (shared across all sub-squares)
                    seep_amount = min(seep_amount, available_capacity)

                    if seep_amount > 0:
                        subsquare.surface_water -= seep_amount
                        tile.water.add_layer_water(exposed_layer, seep_amount)
                        available_capacity -= seep_amount

                    if available_capacity <= 0:
                        break
                if available_capacity <= 0:
                    break


def get_tile_surface_water(tile: "Tile") -> int:
    """Get total surface water across all sub-squares in a tile.

    Useful for compatibility with tile-level systems (evaporation, etc.).
    """
    total = 0
    for row in tile.subgrid:
        for subsquare in row:
            total += subsquare.surface_water
    return total


def remove_water_proportionally(tile: "Tile", amount: int) -> int:
    """Remove water proportionally from tile's sub-squares.

    Each sub-square loses water in proportion to how much it has.
    This ensures water is removed evenly rather than draining one sub-square first.

    Args:
        tile: Tile to remove water from
        amount: Maximum amount to remove

    Returns:
        Actual amount removed (may be less if insufficient water)
    """
    total_water = get_tile_surface_water(tile)
    if total_water <= 0:
        return 0

    to_remove = min(amount, total_water)
    remaining = to_remove

    for row in tile.subgrid:
        for subsquare in row:
            if subsquare.surface_water > 0 and remaining > 0:
                proportion = subsquare.surface_water / total_water
                # Round up to ensure we remove enough, but cap at available and remaining
                take = min(
                    int(to_remove * proportion) + 1,
                    subsquare.surface_water,
                    remaining
                )
                subsquare.surface_water -= take
                remaining -= take

    return to_remove - remaining


def _calculate_elevation_weights(tile: "Tile") -> Tuple[List[Tuple[int, int, float]], float]:
    """Calculate inverse elevation weights for water distribution.

    Uses ABSOLUTE elevation (tile base + subsquare offset) for consistency.
    Lower elevation = higher weight = receives more water.

    Args:
        tile: Tile to calculate weights for

    Returns:
        Tuple of (list of (local_x, local_y, weight), total_weight)
    """
    weights: List[Tuple[int, int, float]] = []
    total_weight = 0.0

    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            abs_elev = get_subsquare_elevation(tile, lx, ly)
            # Inverse weight with offset to prevent division issues
            # +100 ensures positive values even for negative elevations
            weight = 1.0 / (abs_elev + 100.0)
            weights.append((lx, ly, weight))
            total_weight += weight

    return weights, total_weight


def set_tile_surface_water(tile: "Tile", amount: int) -> None:
    """Distribute water amount across tile's sub-squares by elevation.

    Lower sub-squares receive more water (natural pooling behavior).

    Args:
        tile: Tile to distribute water to
        amount: Total water amount to distribute
    """
    # Clear existing water first
    for row in tile.subgrid:
        for subsquare in row:
            subsquare.surface_water = 0

    if amount <= 0:
        return

    weights, total_weight = _calculate_elevation_weights(tile)

    # Distribute proportionally
    distributed = 0
    for i, (lx, ly, weight) in enumerate(weights):
        if i == len(weights) - 1:
            # Last one gets remainder to avoid rounding errors
            portion = amount - distributed
        else:
            portion = int((amount * weight) / total_weight)

        tile.subgrid[lx][ly].surface_water = max(0, portion)
        distributed += portion


def distribute_upward_seepage(
    tile: "Tile",
    water_amount: int,
    active_set: Optional[Set[Point]] = None,
    tile_x: int = 0,
    tile_y: int = 0,
) -> None:
    """Distribute water seeping up from subsurface to sub-squares.

    This now optionally updates the active_water_subsquares set for performance.

    Args:
        tile: Tile receiving upward seepage
        water_amount: Amount of water emerging from below
        active_set: The global set of active water sub-squares to update
        tile_x, tile_y: The tile's world coordinates (for updating active_set)
    """
    if water_amount <= 0:
        return

    weights, total_weight = _calculate_elevation_weights(tile)
    base_sub_x, base_sub_y = tile_to_subgrid(tile_x, tile_y)

    distributed = 0
    for i, (lx, ly, weight) in enumerate(weights):
        if i == len(weights) - 1:
            portion = water_amount - distributed
        else:
            portion = int((water_amount * weight) / total_weight)

        if portion > 0:
            subsquare = tile.subgrid[lx][ly]
            subsquare.surface_water += portion
            subsquare.check_water_threshold()
            if active_set is not None:
                active_set.add((base_sub_x + lx, base_sub_y + ly))
            distributed += portion
