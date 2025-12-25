# simulation/subsurface_vectorized.py
"""
Array-based subsurface water physics with full 3D voxel-like layer adjacency.

This module implements vectorized NumPy operations for subsurface water simulation
at grid resolution (GRID_WIDTH × GRID_HEIGHT), replacing the tile-based approach.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import numpy as np
from scipy.ndimage import binary_dilation

from world.terrain import SoilLayer, MATERIAL_LIBRARY
from config import RAIN_WELLSPRING_MULTIPLIER, GRID_WIDTH, GRID_HEIGHT
from simulation.config import (
    SUBSURFACE_FLOW_RATE,
    VERTICAL_SEEPAGE_RATE,
    CAPILLARY_RISE_RATE,
    SUBSURFACE_FLOW_THRESHOLD,
)

if TYPE_CHECKING:
    from main import GameState


def shift_to_neighbor(flow: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, int]:
    """Shift flow array to neighbor position without edge wrapping.

    Args:
        flow: Array to shift
        dx, dy: Direction offset (-1, 0, or 1)

    Returns:
        (shifted_array, edge_loss) - Shifted array with edges zeroed and total lost to edges
    """
    result = np.zeros_like(flow)
    edge_loss = 0

    # Calculate source and destination slices
    if dx > 0:
        src_x = slice(dx, None)
        dst_x = slice(None, -dx)
        # Track water lost off the far edge (flows out to x = GRID_WIDTH)
        edge_loss += np.sum(flow[:dx, :])
    elif dx < 0:
        src_x = slice(None, dx)
        dst_x = slice(-dx, None)
        # Track water lost off the near edge (flows out to x = -1)
        edge_loss += np.sum(flow[dx:, :])
    else:
        src_x = slice(None)
        dst_x = slice(None)

    if dy > 0:
        src_y = slice(dy, None)
        dst_y = slice(None, -dy)
        # Track water lost off the far edge (flows out to y = GRID_HEIGHT)
        edge_loss += np.sum(flow[:, :dy])
    elif dy < 0:
        src_y = slice(None, dy)
        dst_y = slice(-dy, None)
        # Track water lost off the near edge (flows out to y = -1)
        edge_loss += np.sum(flow[:, dy:])
    else:
        src_y = slice(None)
        dst_y = slice(None)

    result[dst_x, dst_y] = flow[src_x, src_y]
    return result, int(edge_loss)


def compute_layer_elevation_ranges(state: "GameState") -> tuple[np.ndarray, np.ndarray]:
    """Compute bottom and top elevations for all layers.

    Returns:
        (layer_bottom, layer_top) each shape (6, GRID_WIDTH, GRID_HEIGHT)
    """
    layer_bottom = np.zeros((len(SoilLayer), GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)
    layer_bottom[0] = state.bedrock_base  # Bedrock starts at base

    # Cumulative sum up through layers
    for i in range(1, len(SoilLayer)):
        layer_bottom[i] = layer_bottom[i-1] + state.terrain_layers[i-1]

    layer_top = layer_bottom + state.terrain_layers
    return layer_bottom, layer_top


def calculate_max_storage_grid(state: "GameState") -> np.ndarray:
    """Calculate max water storage capacity for all layers.

    Returns:
        Array of shape (6, GRID_WIDTH, GRID_HEIGHT)
    """
    return (state.terrain_layers * state.porosity_grid) // 100


def simulate_vertical_seepage_vectorized(
    state: "GameState",
    active_mask: np.ndarray  # (GRID_WIDTH, GRID_HEIGHT) bool array
) -> np.ndarray:
    """Vectorized vertical seepage for all active grid cells.

    Returns:
        capillary_rise_grid (GRID_WIDTH, GRID_HEIGHT) with amounts to distribute to surface
    """
    # Downward seepage: process layers sequentially to prevent waterfall bug
    # Use delta accumulator for atomic updates
    deltas = np.zeros_like(state.subsurface_water_grid)

    soil_layers = [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                   SoilLayer.SUBSOIL, SoilLayer.REGOLITH]

    for i in range(len(soil_layers) - 1):
        from_layer, to_layer = soil_layers[i], soil_layers[i + 1]

        source_water = state.subsurface_water_grid[from_layer]
        dest_water = state.subsurface_water_grid[to_layer]
        dest_depth = state.terrain_layers[to_layer]
        dest_porosity = state.porosity_grid[to_layer]
        source_perm = state.permeability_vert_grid[from_layer]

        # Calculate capacity
        max_storage = (dest_depth * dest_porosity) // 100
        available_capacity = np.maximum(max_storage - dest_water, 0)

        # Calculate seepage: (source * perm * rate) // 10000
        seep_potential = (source_water * source_perm * VERTICAL_SEEPAGE_RATE) // 10000
        seep_amount = np.minimum.reduce([seep_potential, available_capacity, source_water])

        # Apply only to active regions
        seep_amount = np.where(active_mask, seep_amount, 0)

        # Accumulate transfers
        deltas[from_layer] -= seep_amount
        deltas[to_layer] += seep_amount

    # Apply transfers atomically
    state.subsurface_water_grid += deltas

    # Bedrock pressure: push excess regolith water to subsoil
    max_storage = calculate_max_storage_grid(state)
    excess = np.maximum(state.subsurface_water_grid[SoilLayer.REGOLITH] - max_storage[SoilLayer.REGOLITH], 0)
    excess = np.where(active_mask, excess, 0)
    state.subsurface_water_grid[SoilLayer.REGOLITH] -= excess
    state.subsurface_water_grid[SoilLayer.SUBSOIL] += excess

    # Capillary rise: only where surface is dry (< 10 units)
    dry_surface_mask = state.water_grid < 10
    capillary_rise_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)

    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION]:
        # Mask: active, dry surface, layer has depth and water
        can_rise_mask = (active_mask & dry_surface_mask &
                        (state.terrain_layers[layer] > 0) &
                        (state.subsurface_water_grid[layer] > 0) &
                        (capillary_rise_grid == 0))  # Only rise from first wet layer

        if not np.any(can_rise_mask):
            continue

        source_water = state.subsurface_water_grid[layer]
        source_perm = state.permeability_vert_grid[layer]

        rise_potential = (source_water * source_perm * CAPILLARY_RISE_RATE) // 10000
        rise_amount = np.where(can_rise_mask, rise_potential, 0)

        state.subsurface_water_grid[layer] -= rise_amount
        capillary_rise_grid += rise_amount

    return capillary_rise_grid


def calculate_subsurface_flow_vectorized(
    state: "GameState",
    active_mask: np.ndarray
) -> None:
    """Vectorized subsurface flow with full 3D layer-to-layer adjacency.

    Each soil layer can flow to ALL adjacent layers it physically touches,
    including multiple layers on the same neighbor face (voxel-like physics).

    Modifies state.subsurface_water_grid in place.
    """
    layer_bottom, layer_top = compute_layer_elevation_ranges(state)
    max_storage = calculate_max_storage_grid(state)
    deltas = np.zeros_like(state.subsurface_water_grid)

    flowable_layers = [SoilLayer.REGOLITH, SoilLayer.SUBSOIL, SoilLayer.ELUVIATION,
                       SoilLayer.TOPSOIL, SoilLayer.ORGANICS]

    # Calculate hydraulic head for all layers (water surface elevation)
    water = state.subsurface_water_grid
    layer_depth = layer_top - layer_bottom

    water_height = np.zeros_like(water, dtype=np.int32)
    for layer_idx in range(len(SoilLayer)):
        water_height[layer_idx] = np.divide(
            water[layer_idx] * layer_depth[layer_idx],
            max_storage[layer_idx],
            out=np.zeros_like(water[layer_idx], dtype=np.float32),
            where=max_storage[layer_idx] > 0
        ).astype(np.int32)

    hydraulic_head = layer_bottom + water_height  # Shape: (6, GRID_WIDTH, GRID_HEIGHT)

    # Process each source layer
    for src_layer in flowable_layers:
        src_layer_idx = src_layer

        # Pad ALL layers' elevation data for connectivity checks
        all_layers_bot_padded = np.pad(layer_bottom, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
        all_layers_top_padded = np.pad(layer_top, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
        all_layers_depth_padded = np.pad(state.terrain_layers, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
        all_layers_head_padded = np.pad(hydraulic_head, ((0,0), (1,1), (1,1)), mode='constant', constant_values=-10000)

        center = (slice(1, -1), slice(1, -1))

        # 4 cardinal directions (faces of the voxel)
        neighbor_offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        # Accumulate total pressure differential across all targets
        total_pressure_diff = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.float32)
        flow_targets = []  # List of (target_layer, direction, pressure_diff)

        for dx, dy in neighbor_offsets:
            n_slice = (slice(1 + dx, -1 + dx if -1 + dx != 0 else None),
                      slice(1 + dy, -1 + dy if -1 + dy != 0 else None))

            # My layer's elevation range (source)
            my_bot = layer_bottom[src_layer]
            my_top = layer_top[src_layer]

            # For each potential target layer in the neighbor, check if it touches my layer
            for tgt_layer_idx in range(len(SoilLayer)):
                if tgt_layer_idx == 0:  # Skip bedrock
                    continue

                # Get neighbor's layer elevation range
                neighbor_bot = all_layers_bot_padded[tgt_layer_idx][n_slice]
                neighbor_top = all_layers_top_padded[tgt_layer_idx][n_slice]
                neighbor_depth = all_layers_depth_padded[tgt_layer_idx][n_slice]
                neighbor_head = all_layers_head_padded[tgt_layer_idx][n_slice]

                # Check if layers overlap in elevation (can connect)
                can_connect = (my_bot < neighbor_top) & (neighbor_bot < my_top) & (neighbor_depth > 0)

                if not np.any(can_connect):
                    continue

                # Calculate contact area fraction (how much of my layer touches this neighbor layer)
                # Overlap range: max(my_bot, neighbor_bot) to min(my_top, neighbor_top)
                overlap_bot = np.maximum(my_bot, neighbor_bot)
                overlap_top = np.minimum(my_top, neighbor_top)
                overlap_height = np.maximum(overlap_top - overlap_bot, 0)

                my_layer_height = my_top - my_bot
                # Avoid division by zero
                contact_fraction = np.divide(
                    overlap_height,
                    my_layer_height,
                    out=np.zeros_like(overlap_height, dtype=np.float32),
                    where=my_layer_height > 0
                )

                # Pressure difference (hydraulic gradient)
                my_head = hydraulic_head[src_layer]
                pressure_diff = my_head - neighbor_head
                pressure_diff = np.where(
                    (pressure_diff > SUBSURFACE_FLOW_THRESHOLD) & can_connect,
                    pressure_diff * contact_fraction,  # Weight by contact area
                    0
                )

                if np.any(pressure_diff > 0):
                    flow_targets.append((tgt_layer_idx, dx, dy, pressure_diff))
                    total_pressure_diff += pressure_diff

        # Calculate flow amounts based on permeability and water availability
        src_water = water[src_layer]
        src_perm = state.permeability_horiz_grid[src_layer]
        flow_pct = (src_perm * SUBSURFACE_FLOW_RATE) // 100
        transferable = (src_water * flow_pct) // 100
        transferable = np.where(active_mask, transferable, 0)

        # Track total water lost to edges
        total_edge_loss = 0

        # Distribute flow to all targets proportionally
        for tgt_layer_idx, dx, dy, pressure_diff in flow_targets:
            # Fraction to this specific target
            fraction = np.divide(
                pressure_diff,
                total_pressure_diff,
                out=np.zeros_like(pressure_diff, dtype=np.float64),
                where=total_pressure_diff > 0
            )
            flow = (transferable * fraction).astype(np.int32)

            # Remove from source layer
            deltas[src_layer] -= flow

            # Add to target layer at neighbor position (no wrapping)
            neighbor_flow, edge_loss = shift_to_neighbor(flow, dx, dy)
            deltas[tgt_layer_idx] += neighbor_flow
            total_edge_loss += edge_loss

        # Return water lost to edges back to the pool
        if total_edge_loss > 0:
            state.water_pool.edge_runoff(total_edge_loss)

    # Apply deltas atomically
    state.subsurface_water_grid += deltas
    np.maximum(state.subsurface_water_grid, 0, out=state.subsurface_water_grid)


def calculate_overflows_vectorized(
    state: "GameState",
    active_mask: np.ndarray
) -> np.ndarray:
    """Handle over-capacity layers by distributing to neighbors or surface.

    Returns:
        surface_overflow_grid (GRID_WIDTH, GRID_HEIGHT) with amounts to push to surface
    """
    layer_bottom, layer_top = compute_layer_elevation_ranges(state)
    max_storage = calculate_max_storage_grid(state)
    surface_overflow = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)

    # Process bottom-to-top
    for layer in reversed(SoilLayer):
        if layer == SoilLayer.BEDROCK:
            continue

        # Find over-capacity cells
        overflow_amount = np.maximum(state.subsurface_water_grid[layer] - max_storage[layer], 0)
        overflow_amount = np.where(active_mask, overflow_amount, 0)

        if not np.any(overflow_amount > 0):
            continue

        # Try to distribute to neighbors (similar to horizontal flow but transfer ALL excess)
        hydraulic_head = layer_bottom[layer] + state.terrain_layers[layer]  # Simplified: assume full

        head_padded = np.pad(hydraulic_head, 1, mode='constant', constant_values=-10000)
        layer_bot_padded = np.pad(layer_bottom[layer], 1, mode='constant', constant_values=0)
        layer_top_padded = np.pad(layer_top[layer], 1, mode='constant', constant_values=0)
        layer_depth_padded = np.pad(state.terrain_layers[layer], 1, mode='constant', constant_values=0)

        center = (slice(1, -1), slice(1, -1))
        neighbor_offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        total_diff = np.zeros_like(hydraulic_head, dtype=np.float32)
        neighbor_diffs = []

        for dx, dy in neighbor_offsets:
            n_slice = (slice(1 + dx, -1 + dx if -1 + dx != 0 else None),
                      slice(1 + dy, -1 + dy if -1 + dy != 0 else None))

            neighbor_head = head_padded[n_slice]
            neighbor_bot = layer_bot_padded[n_slice]
            neighbor_top = layer_top_padded[n_slice]
            neighbor_depth = layer_depth_padded[n_slice]

            can_connect = ((layer_bottom[layer] < neighbor_top) &
                          (neighbor_bot < layer_top[layer]) &
                          (neighbor_depth > 0))

            diff = hydraulic_head - neighbor_head
            diff = np.where((diff > 0) & can_connect, diff, 0)

            neighbor_diffs.append((diff, dx, dy))
            total_diff += diff

        # Cells with no viable neighbors push to surface
        no_neighbors_mask = (total_diff == 0) & (overflow_amount > 0)
        surface_overflow += np.where(no_neighbors_mask, overflow_amount, 0)
        state.subsurface_water_grid[layer] -= np.where(no_neighbors_mask, overflow_amount, 0)

        # Distribute to neighbors
        total_edge_loss = 0
        for diff, dx, dy in neighbor_diffs:
            fraction = np.divide(diff, total_diff, out=np.zeros_like(diff, dtype=np.float64), where=total_diff > 0)
            flow = (overflow_amount * fraction).astype(np.int32)

            state.subsurface_water_grid[layer] -= flow
            neighbor_flow, edge_loss = shift_to_neighbor(flow, dx, dy)
            state.subsurface_water_grid[layer] += neighbor_flow
            total_edge_loss += edge_loss

        # Return water lost to edges back to the pool
        if total_edge_loss > 0:
            state.water_pool.edge_runoff(total_edge_loss)

    return surface_overflow


def simulate_subsurface_tick_vectorized(state: "GameState") -> None:
    """Run subsurface simulation using vectorized array operations at grid resolution."""

    # Create active region mask from grid cells with subsurface water (+ neighbors for flow)
    # Start with cells that have water
    water_cells = np.any(state.subsurface_water_grid > 0, axis=0)  # Shape: (GRID_WIDTH, GRID_HEIGHT)

    # Expand to include neighbors (for flow calculations)
    active_mask = binary_dilation(water_cells, iterations=1)  # Expand by 1 cell using scipy

    # Wellsprings: vectorized grid-level processing
    if state.wellspring_grid is not None:
        wellspring_mask = state.wellspring_grid > 0
        if np.any(wellspring_mask):
            multiplier = RAIN_WELLSPRING_MULTIPLIER if state.raining else 100
            desired = (state.wellspring_grid * multiplier) // 100

            # Draw from global water pool
            total_desired = np.sum(desired)
            if total_desired > 0:
                actual_total = state.water_pool.wellspring_draw(total_desired)
                # Distribute proportionally (in case pool is depleted)
                if actual_total < total_desired:
                    actual = (desired * actual_total) // total_desired
                else:
                    actual = desired

                # Add to regolith layer at wellspring locations
                state.subsurface_water_grid[SoilLayer.REGOLITH] += actual
                active_mask |= wellspring_mask

    # Vertical seepage
    capillary_rise_grid = simulate_vertical_seepage_vectorized(state, active_mask)

    # Horizontal flow
    calculate_subsurface_flow_vectorized(state, active_mask)

    # Overflow handling
    surface_overflow_grid = calculate_overflows_vectorized(state, active_mask)

    # Distribute capillary rise and overflow to surface
    total_upward = capillary_rise_grid + surface_overflow_grid
    state.water_grid += total_upward

    # Update active water set (grid-level)
    nz_rows, nz_cols = np.nonzero(state.water_grid)
    state.active_water_cells = set(zip(nz_rows, nz_cols))
