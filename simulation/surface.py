# simulation/surface.py
"""Grid-based surface water flow simulation.

Water flows between grid cells based on elevation differences.
Grid cells are independent units - water flows freely across all cell boundaries.

Key concepts:
- Each grid cell has its own surface_water amount in water_grid
- Flow is 8-directional (cardinal + diagonal)
- Elevation = bedrock_base + sum(terrain_layers)
- Water flows from high to low, distributed proportionally
"""
from __future__ import annotations

from collections import defaultdict
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Set, Union

import numpy as np
from simulation.config import (
    SURFACE_FLOW_RATE,
    SURFACE_FLOW_THRESHOLD,
    SURFACE_SEEPAGE_RATE,
)

if TYPE_CHECKING:
    from main import GameState
    from world_state import GlobalWaterPool

Point = Tuple[int, int]


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
    state.active_water_cells = set(zip(nz_rows, nz_cols))

    # Update water passage accumulators for erosion
    outflow_real = outflow_accum[center_slice]
    nz_out_rows, nz_out_cols = np.nonzero(outflow_real)
    for i in range(len(nz_out_rows)):
        sx, sy = nz_out_rows[i], nz_out_cols[i]

        # Accumulate water passage for erosion
        state.water_passage_grid[sx, sy] += outflow_real[sx, sy]

        # Check visual threshold (using new water value) - add to active set if water visible
        if state.water_grid[sx, sy] > 5:  # Water visible threshold
            state.active_water_cells.add((sx, sy))
    
    return edge_runoff_total


def compute_exposed_layer_grid(terrain_layers: np.ndarray) -> np.ndarray:
    """Compute which layer is topmost (exposed) for each grid cell.

    Returns array of shape (grid_w, grid_h) where values are:
    - 0-4: Layer index (ORGANICS=0, TOPSOIL=1, ELUVIATION=2, SUBSOIL=3, REGOLITH=4)
    - -1: Bedrock only (no soil layers)
    """
    from world.terrain import SoilLayer

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
    from world.terrain import SoilLayer

    # Only process cells with surface water
    if len(state.active_water_cells) == 0:
        return

    # Build active region mask
    rows, cols = zip(*state.active_water_cells)
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
    state.dirty_cells.update(zip(seep_rows, seep_cols))


def remove_water_from_cell_neighborhood(amount: int, state: "GameState", sx: int, sy: int) -> int:
    """Remove water proportionally from a grid cell's 3×3 neighborhood.

    Each grid cell in the neighborhood loses water in proportion to how much it has.
    This ensures water is removed evenly rather than draining one cell first.

    Args:
        amount: Maximum amount to remove
        state: GameState for accessing water_grid
        sx, sy: Grid cell coordinates

    Returns:
        Actual amount removed (may be less if insufficient water)
    """
    from config import GRID_WIDTH, GRID_HEIGHT
    from grid_helpers import get_cell_neighborhood_surface_water

    total_water = get_cell_neighborhood_surface_water(state, sx, sy)
    if total_water <= 0:
        return 0

    to_remove = min(amount, total_water)
    remaining = to_remove

    for dx in range(-1, 2):
        for dy in range(-1, 2):
            gx, gy = sx + dx, sy + dy
            if not (0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT):
                continue

            val = state.water_grid[gx, gy]

            if val > 0 and remaining > 0:
                proportion = val / total_water
                # Round up to ensure we remove enough, but cap at available and remaining
                take = min(
                    int(to_remove * proportion) + 1,
                    val,
                    remaining
                )
                state.water_grid[gx, gy] -= take
                state.active_water_cells.add((gx, gy))
                state.dirty_cells.add((gx, gy))
                remaining -= take

    return to_remove - remaining


def distribute_water_to_cell_neighborhood(
    amount: int,
    state: "GameState",
    sx: int,
    sy: int
) -> List[Tuple[int, int]]:
    """Distribute water to a grid cell's 3×3 neighborhood, filling from lowest elevation up.

    Ensures water surface level remains flat across the connected body.

    Args:
        amount: Amount of water to add
        state: GameState for accessing water_grid and elevation_grid
        sx, sy: Grid cell coordinates

    Returns:
        List of (gx, gy) grid cells that received water
    """
    from config import GRID_WIDTH, GRID_HEIGHT

    if amount <= 0:
        return []

    # 1. Build list of targets in the 3×3 neighborhood
    targets = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            gx, gy = sx + dx, sy + dy
            if not (0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT):
                continue

            base_elev = state.elevation_grid[gx, gy]
            current_water = state.water_grid[gx, gy]
            current_level = base_elev + current_water
            targets.append({
                'gx': gx,
                'gy': gy,
                'level': current_level,
                'added': 0
            })

    # 2. Sort by current level (lowest first)
    targets.sort(key=lambda x: x['level'])

    remaining = amount

    while remaining > 0:
        # Get current lowest level
        min_level = targets[0]['level']

        # Find all cells at this level (the "active group")
        group = []
        for t in targets:
            if t['level'] == min_level:
                group.append(t)
            else:
                break

        if not group:
            break

        # Distribute 1 unit per cell in group
        for t in group:
            if remaining <= 0:
                break
            t['added'] += 1
            t['level'] += 1
            remaining -= 1

        # Re-sort after water addition
        targets.sort(key=lambda x: x['level'])

    # 3. Apply the added water to the grid
    modified = []
    for t in targets:
        if t['added'] > 0:
            state.water_grid[t['gx'], t['gy']] += t['added']
            state.active_water_cells.add((t['gx'], t['gy']))
            state.dirty_cells.add((t['gx'], t['gy']))
            modified.append((t['gx'], t['gy']))

    return modified


def distribute_upward_seepage(
    water_amount: int,
    active_set: Optional[Set[Point]],
    sx: int,
    sy: int,
    state: "GameState",
) -> None:
    """Distribute water seeping up from subsurface to grid cell neighborhood.

    Updates the active_water_cells set for performance optimization.

    Args:
        water_amount: Amount of water emerging from below
        active_set: The global set of active water grid cells to update
        sx, sy: Grid cell coordinates (center of distribution)
        state: The game state, required for water_grid access
    """
    if water_amount <= 0:
        return

    modified = distribute_water_to_cell_neighborhood(water_amount, state, sx, sy)

    if active_set is not None:
        for gx, gy in modified:
            active_set.add((gx, gy))
