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
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Set, Union

import numpy as np
from config import SUBGRID_SIZE
from simulation.config import (
    SURFACE_FLOW_RATE,
    SURFACE_FLOW_THRESHOLD,
    SURFACE_SEEPAGE_RATE,
)
from subgrid import tile_to_subgrid

if TYPE_CHECKING:
    from main import GameState
    from mapgen import Tile
    from world_state import GlobalWaterPool

Point = Tuple[int, int]


def get_subsquare_elevation(tile: "Tile", local_x: int, local_y: int) -> int:
    """Get absolute elevation of a sub-square in depth units."""
    # Tile's terrain surface elevation (in depth units) + sub-square offset
    base_elev = tile.terrain.get_surface_elevation()
    # Convert offset from meters to depth units (1 unit = 0.1m = 100mm)
    offset_units = int(tile.subgrid[local_x][local_y].elevation_offset * 10)
    return base_elev + offset_units


def get_subsquare_water_height(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get water surface height (elevation + water depth) for a sub-square."""
    # NOTE: This function is legacy. For simulation, use the grids directly.
    # It cannot know the water amount without access to the grid.
    elev = get_subsquare_elevation(tile, local_x, local_y)
    return float(elev)


def simulate_surface_flow(state: "GameState") -> int:
    """Simulate surface water flow using vectorized NumPy operations."""
    # 1. Ensure Elevation Grid is up to date
    if state.terrain_changed:
        # This iteration is slow but only happens on terrain modification events
        for x in range(state.width):
            for y in range(state.height):
                tile = state.tiles[x][y]
                base_elev = tile.terrain.get_surface_elevation()
                for lx in range(SUBGRID_SIZE):
                    for ly in range(SUBGRID_SIZE):
                        ss = tile.subgrid[lx][ly]
                        val = base_elev + int(ss.elevation_offset * 10)
                        state.elevation_grid[x * 3 + lx, y * 3 + ly] = val
        state.terrain_changed = False

    water = state.water_grid
    elev = state.elevation_grid
    
    # Pad arrays to handle edges (runoff sink)
    # Pad elevation with a very low value so edges act as sinks
    # Pad water with 0
    H = np.pad(elev + water, 1, mode='constant', constant_values=-10000)
    water_padded = np.pad(water, 1, mode='constant', constant_values=0)
    
    # Accumulators
    deltas = np.zeros_like(water_padded)
    outflow_accum = np.zeros_like(water_padded)
    
    # 2. Vectorized Physics
    # Slices for the center (active) region
    center_slice = (slice(1, -1), slice(1, -1))
    H_center = H[center_slice]
    
    # Calculate total potential difference to all 8 neighbors
    diff_sum = np.zeros_like(H_center, dtype=np.float64)
    diffs = []
    
    # Iterate 8 neighbors (dx, dy)
    # Neighbors relative to center (0,0)
    neighbor_offsets = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1)
    ]
    
    for dx, dy in neighbor_offsets:
        # Shifted view of H representing the neighbor at (x+dx, y+dy)
        # If dx=1, we look at slice(2, None). If dx=-1, slice(0, -2).
        # This aligns the neighbor's value with the center cell's coordinate.
        neighbor_slice = (slice(1 + dx, -1 + dx if -1 + dx != 0 else None), 
                          slice(1 + dy, -1 + dy if -1 + dy != 0 else None))
        
        H_neighbor = H[neighbor_slice]
        d = H_center - H_neighbor
        d = np.maximum(d, 0) # Only flow downhill
        diffs.append((d, dx, dy))
        diff_sum += d
        
    # Calculate flow
    # Mask where flow is possible
    flow_mask = (diff_sum > 0) & (water_padded[center_slice] > 0)
    
    # Amount to move (percentage of current water). Use float to preserve small amounts.
    amount_to_move = water_padded[center_slice] * (SURFACE_FLOW_RATE / 100.0)
    
    # Distribute flow
    for d, dx, dy in diffs:
        # Fraction of flow going to this neighbor
        # Use safe division
        fraction = np.divide(d, diff_sum, out=np.zeros_like(d, dtype=np.float64), where=diff_sum!=0)
        
        # Calculate integer flow amount using probabilistic rounding to prevent stagnation of small volumes
        ideal_flow = amount_to_move * fraction
        flow = np.floor(ideal_flow + np.random.random(ideal_flow.shape)).astype(np.int32)
        
        # Apply flow only where valid
        flow = np.where(flow_mask, flow, 0)
        
        # Subtract from center
        deltas[center_slice] -= flow
        outflow_accum[center_slice] += flow
        
        # Add to neighbor
        neighbor_slice = (slice(1 + dx, -1 + dx if -1 + dx != 0 else None), 
                          slice(1 + dy, -1 + dy if -1 + dy != 0 else None))
        deltas[neighbor_slice] += flow

    # Apply deltas
    water_padded += deltas
    
    # 3. Handle Edge Runoff
    # Calculate how much water ended up in the padding halo
    total_water_after = np.sum(water_padded)
    internal_water_after = np.sum(water_padded[center_slice])
    edge_runoff_total = int(total_water_after - internal_water_after)
    
    if state.water_pool is not None and edge_runoff_total > 0:
        state.water_pool.edge_runoff(edge_runoff_total)

    # 4. Update Active Sets and Accumulators
    # Update the main grid from the padded calculation (discarding halo)
    state.water_grid = water_padded[center_slice].astype(np.int32)

    # Update active set based on non-zero water
    nz_rows, nz_cols = np.nonzero(state.water_grid)
    state.active_water_subsquares = set(zip(nz_rows, nz_cols))

    # Update water passage accumulators for erosion
    outflow_real = outflow_accum[center_slice]
    nz_out_rows, nz_out_cols = np.nonzero(outflow_real)
    for i in range(len(nz_out_rows)):
        sx, sy = nz_out_rows[i], nz_out_cols[i]
        tx, ty = sx // SUBGRID_SIZE, sy // SUBGRID_SIZE
        lx, ly = sx % SUBGRID_SIZE, sy % SUBGRID_SIZE
        subsquare = state.tiles[tx][ty].subgrid[lx][ly]
        subsquare.water_passage += outflow_real[sx, sy]

        # Check visual threshold (using new water value)
        subsquare.check_water_threshold(state.water_grid[sx, sy])
    
    return edge_runoff_total


def simulate_surface_seepage(state: "GameState") -> None:
    """Simulate surface water seeping into the topmost soil layer.

    Water on each sub-square seeps down into the tile's soil based on
    the permeability of the exposed material.

    Args:
        state: The main game state.
    """
    from ground import MATERIAL_LIBRARY, SoilLayer

    # Only iterate active water subsquares for efficiency
    # We need a copy because we might modify the set (though seepage usually just reduces water)
    for sx, sy in list(state.active_water_subsquares):
        water_amt = state.water_grid[sx, sy]
        if water_amt <= 0:
            continue

        tx, ty = sx // SUBGRID_SIZE, sy // SUBGRID_SIZE
        lx, ly = sx % SUBGRID_SIZE, sy % SUBGRID_SIZE
        tile = state.tiles[tx][ty]

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

        # Calculate seepage amount based on permeability
        seep_rate = (SURFACE_SEEPAGE_RATE * props.permeability_vertical) // 100
        seep_amount = (water_amt * seep_rate) // 100
        seep_amount = min(seep_amount, available_capacity)

        if seep_amount > 0:
            state.water_grid[sx, sy] -= seep_amount
            tile.water.add_layer_water(exposed_layer, seep_amount)

            # Update visual if threshold crossed
            tile.subgrid[lx][ly].check_water_threshold(state.water_grid[sx, sy])


def get_tile_surface_water(tile: "Tile", water_grid: np.ndarray | None = None, tile_x: int = -1, tile_y: int = -1) -> int:
    """Get total surface water across all sub-squares in a tile.

    Useful for compatibility with tile-level systems (evaporation, etc.).
    """
    if water_grid is None or tile_x == -1:
        # Fallback for legacy calls that don't have grid access.
        # This is now incorrect as subsquare.surface_water is gone.
        # The correct fix is to update all call sites.
        # For now, returning 0 to avoid crashing.
        return 0

    sx = tile_x * SUBGRID_SIZE
    sy = tile_y * SUBGRID_SIZE

    # Sum the 3x3 block
    return np.sum(water_grid[sx:sx+3, sy:sy+3])


def remove_water_proportionally(tile: "Tile", amount: int, state: "GameState", tile_x: int, tile_y: int) -> int:
    """Remove water proportionally from tile's sub-squares.

    Each sub-square loses water in proportion to how much it has.
    This ensures water is removed evenly rather than draining one sub-square first.

    Args:
        tile: Tile to remove water from
        amount: Maximum amount to remove

    Returns:
        Actual amount removed (may be less if insufficient water)
    """
    total_water = get_tile_surface_water(tile, state.water_grid, tile_x, tile_y)
    if total_water <= 0:
        return 0

    to_remove = min(amount, total_water)
    remaining = to_remove

    sx_base = tile_x * SUBGRID_SIZE
    sy_base = tile_y * SUBGRID_SIZE

    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            sx, sy = sx_base + lx, sy_base + ly
            val = state.water_grid[sx, sy]

            if val > 0 and remaining > 0:
                proportion = val / total_water
                # Round up to ensure we remove enough, but cap at available and remaining
                take = min(
                    int(to_remove * proportion) + 1,
                    val,
                    remaining
                )
                state.water_grid[sx, sy] -= take
                remaining -= take
                tile.subgrid[lx][ly].check_water_threshold(state.water_grid[sx, sy])

    return to_remove - remaining


def distribute_water_to_tile(tile: "Tile", amount: int, water_grid: np.ndarray, tile_x: int, tile_y: int) -> List[Tuple[int, int]]:
    """
    Distribute water to a tile's sub-squares, filling from lowest absolute elevation up.
    Ensures water surface level remains flat across the connected body within the tile.

    Args:
        tile: The tile to distribute water to
        amount: Amount of water to add
        water_grid: The global water grid to modify
        tile_x, tile_y: Coordinates of the tile for grid indexing

    Returns:
        List of (local_x, local_y) indices that received water.
    """
    if amount <= 0:
        return []

    sx_base = tile_x * SUBGRID_SIZE
    sy_base = tile_y * SUBGRID_SIZE

    # 1. Build list of targets with current absolute elevation
    targets = []
    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            ss = tile.subgrid[lx][ly]
            # Use absolute elevation helper for correctness
            base_elev = get_subsquare_elevation(tile, lx, ly)
            current_water = water_grid[sx_base + lx, sy_base + ly]
            current_level = base_elev + current_water
            targets.append({
                'lx': lx,
                'ly': ly,
                'sx': sx_base + lx,
                'sy': sy_base + ly,
                'ss': ss,
                'level': current_level,
                'added': 0
            })

    # 2. Sort by current level (lowest first)
    targets.sort(key=lambda x: x['level'])

    remaining = amount

    while remaining > 0:
        # Get current lowest level
        min_level = targets[0]['level']

        # Find all subsquares at this level (the "active group")
        group = []
        for t in targets:
            if t['level'] == min_level:
                group.append(t)
            else:
                break

        # Find the next elevation level to reach
        if len(group) < len(targets):
            next_level = targets[len(group)]['level']
            diff = next_level - min_level
        else:
            # No higher level, we are at the top. Treat remaining space as infinite.
            diff = remaining

        # Calculate volume needed to raise the active group to the next level
        needed = diff * len(group)

        if needed > 0:
            if remaining >= needed:
                # We have enough water to raise the whole group to the next level
                fill_per = diff
                for t in group:
                    t['added'] += fill_per
                    t['level'] += fill_per
                remaining -= needed
            else:
                # We can only partially raise the group
                count = len(group)
                per_share = remaining // count
                rem = remaining % count
                # Shuffle group to avoid spatial bias in remainder distribution
                random.shuffle(group)
                
                for i, t in enumerate(group):
                    add = per_share + (1 if i < rem else 0)
                    t['added'] += add
                    t['level'] += add
                remaining = 0
        else:
            # Should not happen if logic is correct, but prevents infinite loop
            break

    # 3. Apply changes to the actual sub-squares
    modified_indices = []
    for t in targets:
        if t['added'] > 0:
            water_grid[t['sx'], t['sy']] += t['added']
            t['ss'].check_water_threshold(water_grid[t['sx'], t['sy']])
            modified_indices.append((t['lx'], t['ly']))

    return modified_indices


def distribute_upward_seepage(
    tile: "Tile",
    water_amount: int,
    active_set: Optional[Set[Point]] = None,
    tile_x: int = 0,
    tile_y: int = 0,
    state: "GameState" = None,
) -> None:
    """Distribute water seeping up from subsurface to sub-squares.

    This now optionally updates the active_water_subsquares set for performance.

    Args:
        tile: Tile receiving upward seepage
        water_amount: Amount of water emerging from below
        active_set: The global set of active water sub-squares to update
        tile_x, tile_y: The tile's world coordinates (for updating active_set)
        state: The game state, required for water_grid access
    """
    if water_amount <= 0:
        return

    if state is None or state.water_grid is None:
        return  # Cannot proceed without the water grid

    modified = distribute_water_to_tile(tile, water_amount, state.water_grid, tile_x, tile_y)

    if active_set is not None:
        base_sub_x, base_sub_y = tile_to_subgrid(tile_x, tile_y)
        for lx, ly in modified:
            active_set.add((base_sub_x + lx, base_sub_y + ly))
