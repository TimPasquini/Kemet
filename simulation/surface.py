# simulation/surface.py
"""Sub-grid surface water flow simulation.

Water flows between sub-squares based on elevation differences.
Flow crosses tile boundaries seamlessly - sub-squares are independent units.

Key concepts:
- Each sub-square has its own surface_water amount
- Flow is 8-directional (cardinal + diagonal)
- Elevation = bedrock_base + sum(terrain_layers)
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
    """Get absolute elevation of a sub-square in depth units.

    DEPRECATED: This function is legacy. Use elevation_grid[sx, sy] directly.
    """
    # Legacy function - returns tile's terrain surface elevation
    return tile.terrain.get_surface_elevation()


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
        # Vectorized rebuild: bedrock + all terrain layers
        state.elevation_grid = (
            state.bedrock_base +
            np.sum(state.terrain_layers, axis=0)
        )
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

        # Accumulate water passage for erosion
        state.water_passage_grid[sx, sy] += outflow_real[sx, sy]

        # Check visual threshold (using new water value) - add to active set if water visible
        if state.water_grid[sx, sy] > 5:  # Water visible threshold
            state.active_water_subsquares.add((sx, sy))
    
    return edge_runoff_total


def compute_exposed_layer_grid(terrain_layers: np.ndarray) -> np.ndarray:
    """Compute which layer is topmost (exposed) for each grid cell.

    Returns array of shape (grid_w, grid_h) where values are:
    - 0-4: Layer index (ORGANICS=0, TOPSOIL=1, ELUVIATION=2, SUBSOIL=3, REGOLITH=4)
    - -1: Bedrock only (no soil layers)
    """
    from ground import SoilLayer

    # Start with all bedrock (-1)
    exposed = np.full(terrain_layers.shape[1:], -1, dtype=np.int8)

    # Check layers from bottom to top (so top layer overwrites)
    # Layer indices: ORGANICS=0, TOPSOIL=1, ELUVIATION=2, SUBSOIL=3, REGOLITH=4
    for layer_idx in [SoilLayer.REGOLITH, SoilLayer.SUBSOIL, SoilLayer.ELUVIATION,
                      SoilLayer.TOPSOIL, SoilLayer.ORGANICS]:
        mask = terrain_layers[layer_idx] > 0
        exposed[mask] = layer_idx

    return exposed


def simulate_surface_seepage(state: "GameState") -> None:
    """Simulate surface water seeping into the topmost soil layer (vectorized).

    Water on each grid cell seeps down into the topmost non-bedrock soil layer
    based on the permeability of the exposed material.

    Args:
        state: The main game state.
    """
    from ground import SoilLayer

    # Only process cells with surface water
    if len(state.active_water_subsquares) == 0:
        return

    # Build active region mask
    rows, cols = zip(*state.active_water_subsquares)
    rows = np.array(rows, dtype=np.int32)
    cols = np.array(cols, dtype=np.int32)

    # Get water amounts for active cells
    water_amounts = state.water_grid[rows, cols]

    # Compute exposed layer for all cells (cached computation)
    exposed_grid = compute_exposed_layer_grid(state.terrain_layers)
    exposed_layers = exposed_grid[rows, cols]

    # Filter out bedrock-only cells and zero-water cells
    valid_mask = (exposed_layers >= 0) & (water_amounts > 0)
    if not np.any(valid_mask):
        return

    rows = rows[valid_mask]
    cols = cols[valid_mask]
    water_amounts = water_amounts[valid_mask]
    exposed_layers = exposed_layers[valid_mask]

    # Gather properties using fancy indexing
    permeability = state.permeability_vert_grid[exposed_layers, rows, cols]
    layer_depth = state.terrain_layers[exposed_layers, rows, cols]
    porosity = state.porosity_grid[exposed_layers, rows, cols]
    current_water = state.subsurface_water_grid[exposed_layers, rows, cols]

    # Vectorized capacity calculation
    max_storage = (layer_depth * porosity) // 100
    available_capacity = max_storage - current_water

    # Vectorized seepage calculation
    seep_rate = (SURFACE_SEEPAGE_RATE * permeability) // 100
    seep_amount = (water_amounts * seep_rate) // 100
    seep_amount = np.minimum(seep_amount, available_capacity)

    # Apply seepage where amount > 0 and permeability > 0
    apply_mask = (seep_amount > 0) & (permeability > 0) & (available_capacity > 0)
    if not np.any(apply_mask):
        return

    # Filter to cells that actually seep
    seep_rows = rows[apply_mask]
    seep_cols = cols[apply_mask]
    seep_layers = exposed_layers[apply_mask]
    seep_amounts = seep_amount[apply_mask]

    # Update grids
    state.water_grid[seep_rows, seep_cols] -= seep_amounts
    state.subsurface_water_grid[seep_layers, seep_rows, seep_cols] += seep_amounts

    # Mark dirty for rendering (legacy compatibility)
    state.dirty_subsquares.update(zip(seep_rows, seep_cols))


def get_tile_surface_water(tile: Optional["Tile"] = None, water_grid: np.ndarray | None = None, tile_x: int = -1, tile_y: int = -1) -> int:
    """Get total surface water across all sub-squares in a tile.

    Args:
        tile: DEPRECATED - no longer used, pass None
        water_grid: The water grid to sum from
        tile_x, tile_y: Tile coordinates

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


def remove_water_proportionally(tile: Optional["Tile"], amount: int, state: "GameState", tile_x: int, tile_y: int) -> int:
    """Remove water proportionally from tile's sub-squares.

    Each sub-square loses water in proportion to how much it has.
    This ensures water is removed evenly rather than draining one sub-square first.

    Args:
        tile: DEPRECATED - no longer used, pass None
        amount: Maximum amount to remove
        state: GameState for accessing water_grid
        tile_x, tile_y: Tile coordinates

    Returns:
        Actual amount removed (may be less if insufficient water)
    """
    total_water = get_tile_surface_water(None, state.water_grid, tile_x, tile_y)
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

    return to_remove - remaining


def distribute_water_to_tile(
    tile: Optional["Tile"],
    amount: int,
    water_grid: np.ndarray,
    tile_x: int,
    tile_y: int,
    state: Optional["GameState"] = None
) -> List[Tuple[int, int]]:
    """
    Distribute water to a tile's sub-squares, filling from lowest absolute elevation up.
    Ensures water surface level remains flat across the connected body within the tile.

    Args:
        tile: DEPRECATED - no longer used, pass None
        amount: Amount of water to add
        water_grid: The global water grid to modify
        tile_x, tile_y: Coordinates of the tile for grid indexing
        state: GameState for accessing elevation_grid

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
            sx = sx_base + lx
            sy = sy_base + ly
            # Get elevation from grid if available, otherwise from tile (legacy)
            if state is not None and state.elevation_grid is not None:
                base_elev = state.elevation_grid[sx, sy]
            else:
                # Legacy fallback
                base_elev = get_subsquare_elevation(tile, lx, ly) if tile else 0
            current_water = water_grid[sx, sy]
            current_level = base_elev + current_water
            targets.append({
                'lx': lx,
                'ly': ly,
                'sx': sx,
                'sy': sy,
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
            modified_indices.append((t['lx'], t['ly']))

    return modified_indices


def distribute_upward_seepage(
    tile: Optional["Tile"],
    water_amount: int,
    active_set: Optional[Set[Point]] = None,
    tile_x: int = 0,
    tile_y: int = 0,
    state: "GameState" = None,
) -> None:
    """Distribute water seeping up from subsurface to sub-squares.

    This now optionally updates the active_water_subsquares set for performance.

    Args:
        tile: DEPRECATED - no longer used, pass None
        water_amount: Amount of water emerging from below
        active_set: The global set of active water sub-squares to update
        tile_x, tile_y: The tile's world coordinates (for updating active_set)
        state: The game state, required for water_grid access
    """
    if water_amount <= 0:
        return

    if state is None or state.water_grid is None:
        return  # Cannot proceed without the water grid

    modified = distribute_water_to_tile(None, water_amount, state.water_grid, tile_x, tile_y, state)

    if active_set is not None:
        base_sub_x, base_sub_y = tile_to_subgrid(tile_x, tile_y)
        for lx, ly in modified:
            active_set.add((base_sub_x + lx, base_sub_y + ly))
