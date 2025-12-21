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
    elev = get_subsquare_elevation(tile, local_x, local_y)
    water = tile.subgrid[local_x][local_y].surface_water
    return elev + water


def sync_objects_to_arrays(state: "GameState") -> None:
    """Sync data from GameState objects to NumPy arrays."""
    w, h = state.width * SUBGRID_SIZE, state.height * SUBGRID_SIZE

    # Initialize arrays if needed
    if state.water_grid is None or state.water_grid.shape != (w, h):
        state.water_grid = np.zeros((w, h), dtype=np.int32)
        state.elevation_grid = np.zeros((w, h), dtype=np.int32)
        state.terrain_changed = True

    # Rebuild elevation grid if terrain changed
    if state.terrain_changed:
        # This iteration is slow but only happens on terrain modification events
        for x in range(state.width):
            for y in range(state.height):
                tile = state.tiles[x][y]
                base_elev = tile.terrain.get_surface_elevation()
                for lx in range(SUBGRID_SIZE):
                    for ly in range(SUBGRID_SIZE):
                        ss = tile.subgrid[lx][ly]
                        # Convert offset (meters) to units (100mm)
                        # offset 0.1m = 1 unit
                        val = base_elev + int(ss.elevation_offset * 10)
                        state.elevation_grid[x * 3 + lx, y * 3 + ly] = val
        state.terrain_changed = False

    # Sync water from active objects to grid
    # We zero out the grid and rebuild from active set to ensure consistency
    state.water_grid.fill(0)
    for sx, sy in state.active_water_subsquares:
        tx, ty = sx // SUBGRID_SIZE, sy // SUBGRID_SIZE
        lx, ly = sx % SUBGRID_SIZE, sy % SUBGRID_SIZE
        val = state.tiles[tx][ty].subgrid[lx][ly].surface_water
        state.water_grid[sx, sy] = val


def sync_arrays_to_objects(state: "GameState", outflow_grid: np.ndarray) -> None:
    """Sync data from NumPy arrays back to GameState objects."""
    # Identify all cells that need updates:
    # 1. Cells that were active before (might have dried up)
    # 2. Cells that are non-zero in the new grid (might be newly wet)
    
    old_active = state.active_water_subsquares.copy()
    state.active_water_subsquares.clear()
    
    # Find currently wet cells
    nz_rows, nz_cols = np.nonzero(state.water_grid)
    current_wet_coords = set(zip(nz_rows, nz_cols))
    
    # Update active set
    state.active_water_subsquares.update(current_wet_coords)
    
    # Union of old and new ensures we update cells that just dried out (to 0)
    update_set = old_active.union(current_wet_coords)
    
    for sx, sy in update_set:
        tx, ty = sx // SUBGRID_SIZE, sy // SUBGRID_SIZE
        lx, ly = sx % SUBGRID_SIZE, sy % SUBGRID_SIZE
        subsquare = state.tiles[tx][ty].subgrid[lx][ly]
        
        # Update water level
        subsquare.surface_water = int(state.water_grid[sx, sy])
        
        # Accumulate water passage (for erosion)
        outflow = int(outflow_grid[sx, sy])
        if outflow > 0:
            subsquare.water_passage += outflow
            
        # Update visual state
        subsquare.check_water_threshold()


def simulate_surface_flow(state: "GameState") -> int:
    """Simulate surface water flow using vectorized NumPy operations."""
    
    # 1. Sync In
    sync_objects_to_arrays(state)
    
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

    # 4. Sync Out
    # Update the main grid from the padded calculation (discarding halo)
    state.water_grid = water_padded[center_slice].astype(np.int32)
    
    # Sync back to objects
    sync_arrays_to_objects(state, outflow_accum[center_slice])
    
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

    distribute_water_to_tile(tile, amount)


def distribute_water_to_tile(tile: "Tile", amount: int) -> List[Tuple[int, int]]:
    """
    Distribute water to a tile's sub-squares, filling from lowest absolute elevation up.
    Ensures water surface level remains flat across the connected body within the tile.

    Args:
        tile: The tile to distribute water to
        amount: Amount of water to add

    Returns:
        List of (local_x, local_y) indices that received water.
    """
    if amount <= 0:
        return []

    # 1. Build list of targets with current absolute elevation
    targets = []
    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            ss = tile.subgrid[lx][ly]
            # Use absolute elevation helper for correctness
            base_elev = get_subsquare_elevation(tile, lx, ly)
            current_level = base_elev + ss.surface_water
            targets.append({
                'lx': lx,
                'ly': ly,
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
            t['ss'].surface_water += t['added']
            t['ss'].check_water_threshold()
            modified_indices.append((t['lx'], t['ly']))

    return modified_indices


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

    modified = distribute_water_to_tile(tile, water_amount)

    if active_set is not None:
        base_sub_x, base_sub_y = tile_to_subgrid(tile_x, tile_y)
        for lx, ly in modified:
            active_set.add((base_sub_x + lx, base_sub_y + ly))
