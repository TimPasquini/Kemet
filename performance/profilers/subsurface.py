#!/usr/bin/env python3
"""
Detailed profiling for subsurface simulation bottlenecks.

This tool breaks down the subsurface simulation to identify specific bottlenecks
within the vectorized water flow calculations.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path so we can import from main project
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from typing import Dict, List
from statistics import mean, median
from dataclasses import dataclass, field

import numpy as np

from game_state import build_initial_state, GameState
from core.config import GRID_WIDTH, GRID_HEIGHT


@dataclass
class FunctionProfile:
    """Profile data for a single function."""
    name: str
    call_count: int = 0
    total_time: float = 0.0
    times: List[float] = field(default_factory=list)

    def record(self, duration: float):
        """Record a function call."""
        self.call_count += 1
        self.total_time += duration
        self.times.append(duration)

    def avg_time_ms(self) -> float:
        """Average time in milliseconds."""
        return (self.total_time / self.call_count * 1000) if self.call_count > 0 else 0

    def median_time_ms(self) -> float:
        """Median time in milliseconds."""
        return median(self.times) * 1000 if self.times else 0

    def pct_of_total(self, total_time: float) -> float:
        """Percentage of total runtime."""
        return (self.total_time / total_time * 100) if total_time > 0 else 0


class SubsurfaceProfiler:
    """Detailed profiler for subsurface simulation."""

    def __init__(self):
        self.profiles: Dict[str, FunctionProfile] = {}
        self.total_subsurface_time: float = 0.0

    def get_profile(self, name: str) -> FunctionProfile:
        """Get or create a profile for a function."""
        if name not in self.profiles:
            self.profiles[name] = FunctionProfile(name)
        return self.profiles[name]

    def profile_subsurface_tick(self, state: GameState) -> float:
        """Profile a single subsurface tick with detailed breakdowns."""
        tick_start = time.perf_counter()

        # Import here to avoid circular dependencies
        from scipy.ndimage import binary_dilation
        from world.terrain import SoilLayer
        from core.config import RAIN_WELLSPRING_MULTIPLIER

        # ========== Active Mask Creation ==========
        mask_start = time.perf_counter()
        water_cells = np.any(state.subsurface_water_grid > 0, axis=0)
        active_mask = binary_dilation(water_cells, iterations=1)
        self.get_profile("1_active_mask").record(time.perf_counter() - mask_start)

        # ========== Wellsprings ==========
        well_start = time.perf_counter()
        if state.wellspring_grid is not None:
            wellspring_mask = state.wellspring_grid > 0
            if np.any(wellspring_mask):
                multiplier = RAIN_WELLSPRING_MULTIPLIER if state.raining else 100
                desired = (state.wellspring_grid * multiplier) // 100
                total_desired = np.sum(desired)
                if total_desired > 0:
                    actual_total = state.water_pool.wellspring_draw(total_desired)
                    if actual_total < total_desired:
                        actual = (desired * actual_total) // total_desired
                    else:
                        actual = desired
                    state.subsurface_water_grid[SoilLayer.REGOLITH] += actual
                    active_mask |= wellspring_mask
        self.get_profile("2_wellsprings").record(time.perf_counter() - well_start)

        # ========== Vertical Seepage ==========
        vert_start = time.perf_counter()
        capillary_rise_grid = self.profile_vertical_seepage(state, active_mask)
        self.get_profile("3_vertical_seepage").record(time.perf_counter() - vert_start)

        # ========== Horizontal Flow ==========
        horiz_start = time.perf_counter()
        self.profile_horizontal_flow(state, active_mask)
        self.get_profile("4_horizontal_flow").record(time.perf_counter() - horiz_start)

        # ========== Overflow Handling ==========
        overflow_start = time.perf_counter()
        surface_overflow_grid = self.profile_overflows(state, active_mask)
        self.get_profile("5_overflow_handling").record(time.perf_counter() - overflow_start)

        # ========== Surface Distribution ==========
        surf_start = time.perf_counter()
        total_upward = capillary_rise_grid + surface_overflow_grid
        state.water_grid += total_upward
        nz_rows, nz_cols = np.nonzero(state.water_grid)
        state.active_water_cells = set(zip(nz_rows, nz_cols))
        self.get_profile("6_surface_distribution").record(time.perf_counter() - surf_start)

        tick_time = time.perf_counter() - tick_start
        self.total_subsurface_time += tick_time
        return tick_time

    def profile_vertical_seepage(self, state: GameState, active_mask: np.ndarray) -> np.ndarray:
        """Profile vertical seepage with sub-breakdowns."""
        from world.terrain import SoilLayer
        from simulation.config import VERTICAL_SEEPAGE_RATE, CAPILLARY_RISE_RATE

        # Downward seepage
        down_start = time.perf_counter()
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

            max_storage = (dest_depth * dest_porosity) // 100
            available_capacity = np.maximum(max_storage - dest_water, 0)
            seep_potential = (source_water * source_perm * VERTICAL_SEEPAGE_RATE) // 10000
            seep_amount = np.minimum.reduce([seep_potential, available_capacity, source_water])
            seep_amount = np.where(active_mask, seep_amount, 0)

            deltas[from_layer] -= seep_amount
            deltas[to_layer] += seep_amount

        state.subsurface_water_grid += deltas
        self.get_profile("3a_downward_seepage").record(time.perf_counter() - down_start)

        # Bedrock pressure
        pressure_start = time.perf_counter()
        from simulation.subsurface_vectorized import calculate_max_storage_grid
        max_storage = calculate_max_storage_grid(state)
        excess = np.maximum(state.subsurface_water_grid[SoilLayer.REGOLITH] - max_storage[SoilLayer.REGOLITH], 0)
        excess = np.where(active_mask, excess, 0)
        state.subsurface_water_grid[SoilLayer.REGOLITH] -= excess
        state.subsurface_water_grid[SoilLayer.SUBSOIL] += excess
        self.get_profile("3b_bedrock_pressure").record(time.perf_counter() - pressure_start)

        # Capillary rise
        cap_start = time.perf_counter()
        dry_surface_mask = state.water_grid < 10
        capillary_rise_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)

        for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION]:
            can_rise_mask = (active_mask & dry_surface_mask &
                            (state.terrain_layers[layer] > 0) &
                            (state.subsurface_water_grid[layer] > 0) &
                            (capillary_rise_grid == 0))

            if not np.any(can_rise_mask):
                continue

            source_water = state.subsurface_water_grid[layer]
            source_perm = state.permeability_vert_grid[layer]
            rise_potential = (source_water * source_perm * CAPILLARY_RISE_RATE) // 10000
            rise_amount = np.where(can_rise_mask, rise_potential, 0)

            state.subsurface_water_grid[layer] -= rise_amount
            capillary_rise_grid += rise_amount

        self.get_profile("3c_capillary_rise").record(time.perf_counter() - cap_start)
        return capillary_rise_grid

    def profile_horizontal_flow(self, state: GameState, active_mask: np.ndarray) -> None:
        """Profile horizontal flow with detailed sub-breakdowns."""
        from world.terrain import SoilLayer
        from simulation.config import SUBSURFACE_FLOW_RATE, SUBSURFACE_FLOW_THRESHOLD
        from simulation.subsurface_vectorized import (
            compute_layer_elevation_ranges,
            calculate_max_storage_grid,
            shift_to_neighbor
        )

        # Setup
        setup_start = time.perf_counter()
        layer_bottom, layer_top = compute_layer_elevation_ranges(state)
        max_storage = calculate_max_storage_grid(state)
        deltas = np.zeros_like(state.subsurface_water_grid)
        flowable_layers = [SoilLayer.REGOLITH, SoilLayer.SUBSOIL, SoilLayer.ELUVIATION,
                           SoilLayer.TOPSOIL, SoilLayer.ORGANICS]
        self.get_profile("4a_flow_setup").record(time.perf_counter() - setup_start)

        # Calculate hydraulic head
        head_start = time.perf_counter()
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
        hydraulic_head = layer_bottom + water_height
        self.get_profile("4b_hydraulic_head").record(time.perf_counter() - head_start)

        # Process each source layer
        layer_process_time = 0.0
        padding_time = 0.0
        connectivity_time = 0.0
        flow_calc_time = 0.0
        flow_apply_time = 0.0

        for src_layer in flowable_layers:
            layer_start = time.perf_counter()

            # Padding
            pad_start = time.perf_counter()
            all_layers_bot_padded = np.pad(layer_bottom, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
            all_layers_top_padded = np.pad(layer_top, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
            all_layers_depth_padded = np.pad(state.terrain_layers, ((0,0), (1,1), (1,1)), mode='constant', constant_values=0)
            all_layers_head_padded = np.pad(hydraulic_head, ((0,0), (1,1), (1,1)), mode='constant', constant_values=-10000)
            padding_time += time.perf_counter() - pad_start

            # Connectivity checks
            conn_start = time.perf_counter()
            neighbor_offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            total_pressure_diff = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.float32)
            flow_targets = []

            my_bot = layer_bottom[src_layer]
            my_top = layer_top[src_layer]

            for dx, dy in neighbor_offsets:
                n_slice = (slice(1 + dx, -1 + dx if -1 + dx != 0 else None),
                          slice(1 + dy, -1 + dy if -1 + dy != 0 else None))

                for tgt_layer_idx in range(len(SoilLayer)):
                    if tgt_layer_idx == 0:
                        continue

                    neighbor_bot = all_layers_bot_padded[tgt_layer_idx][n_slice]
                    neighbor_top = all_layers_top_padded[tgt_layer_idx][n_slice]
                    neighbor_depth = all_layers_depth_padded[tgt_layer_idx][n_slice]
                    neighbor_head = all_layers_head_padded[tgt_layer_idx][n_slice]

                    can_connect = (my_bot < neighbor_top) & (neighbor_bot < my_top) & (neighbor_depth > 0)

                    if not np.any(can_connect):
                        continue

                    overlap_bot = np.maximum(my_bot, neighbor_bot)
                    overlap_top = np.minimum(my_top, neighbor_top)
                    overlap_height = np.maximum(overlap_top - overlap_bot, 0)
                    my_layer_height = my_top - my_bot
                    contact_fraction = np.divide(
                        overlap_height,
                        my_layer_height,
                        out=np.zeros_like(overlap_height, dtype=np.float32),
                        where=my_layer_height > 0
                    )

                    my_head = hydraulic_head[src_layer]
                    pressure_diff = my_head - neighbor_head
                    pressure_diff = np.where(
                        (pressure_diff > SUBSURFACE_FLOW_THRESHOLD) & can_connect,
                        pressure_diff * contact_fraction,
                        0
                    )

                    if np.any(pressure_diff > 0):
                        flow_targets.append((tgt_layer_idx, dx, dy, pressure_diff))
                        total_pressure_diff += pressure_diff

            connectivity_time += time.perf_counter() - conn_start

            # Flow calculation
            calc_start = time.perf_counter()
            src_water = water[src_layer]
            src_perm = state.permeability_horiz_grid[src_layer]
            flow_pct = (src_perm * SUBSURFACE_FLOW_RATE) // 100
            transferable = (src_water * flow_pct) // 100
            transferable = np.where(active_mask, transferable, 0)
            flow_calc_time += time.perf_counter() - calc_start

            # Flow application
            apply_start = time.perf_counter()
            total_edge_loss = 0
            for tgt_layer_idx, dx, dy, pressure_diff in flow_targets:
                fraction = np.divide(
                    pressure_diff,
                    total_pressure_diff,
                    out=np.zeros_like(pressure_diff, dtype=np.float64),
                    where=total_pressure_diff > 0
                )
                flow = (transferable * fraction).astype(np.int32)
                deltas[src_layer] -= flow
                neighbor_flow, edge_loss = shift_to_neighbor(flow, dx, dy)
                deltas[tgt_layer_idx] += neighbor_flow
                total_edge_loss += edge_loss

            if total_edge_loss > 0:
                state.water_pool.edge_runoff(total_edge_loss)

            flow_apply_time += time.perf_counter() - apply_start
            layer_process_time += time.perf_counter() - layer_start

        # Record sub-timings
        self.get_profile("4c_layer_padding").record(padding_time)
        self.get_profile("4d_connectivity_checks").record(connectivity_time)
        self.get_profile("4e_flow_calculation").record(flow_calc_time)
        self.get_profile("4f_flow_application").record(flow_apply_time)

        # Apply deltas
        apply_start = time.perf_counter()
        state.subsurface_water_grid += deltas
        np.maximum(state.subsurface_water_grid, 0, out=state.subsurface_water_grid)
        self.get_profile("4g_delta_application").record(time.perf_counter() - apply_start)

    def profile_overflows(self, state: GameState, active_mask: np.ndarray) -> np.ndarray:
        """Profile overflow handling (simplified - not fully detailed)."""
        from simulation.subsurface_vectorized import calculate_overflows_vectorized
        return calculate_overflows_vectorized(state, active_mask)

    def print_report(self):
        """Print detailed profiling report."""
        print("\n" + "="*80)
        print("SUBSURFACE SIMULATION DETAILED PROFILE")
        print(f"Grid Size: {GRID_WIDTH}×{GRID_HEIGHT} cells")
        print("="*80)

        # Sort by total time
        sorted_profiles = sorted(self.profiles.values(), key=lambda p: p.total_time, reverse=True)

        print(f"\n{'Function':<40} {'Calls':<8} {'Total (ms)':<12} {'Avg (ms)':<12} {'% Time':<8}")
        print("-"*80)

        for profile in sorted_profiles:
            print(f"{profile.name:<40} {profile.call_count:<8} {profile.total_time*1000:<12.2f} "
                  f"{profile.avg_time_ms():<12.2f} {profile.pct_of_total(self.total_subsurface_time):<8.1f}")

        print("-"*80)
        print(f"{'TOTAL SUBSURFACE TIME':<40} {'':<8} {self.total_subsurface_time*1000:<12.2f} {'':<12} {'100.0':<8}")
        print("="*80)


def run_subsurface_profile(num_subsurface_ticks: int = 250) -> SubsurfaceProfiler:
    """
    Run a focused subsurface profiling session.

    Since subsurface runs every 4 ticks, we need 4× ticks to get the desired subsurface count.
    """
    print(f"\n🔬 Profiling subsurface simulation ({num_subsurface_ticks} subsurface ticks)...")
    print("  Initializing game state...")

    state = build_initial_state()
    profiler = SubsurfaceProfiler()

    # Run enough ticks to get the desired number of subsurface updates
    total_ticks = num_subsurface_ticks * 4
    subsurface_count = 0

    print(f"  Running {total_ticks} total ticks (subsurface every 4th tick)...")

    for tick in range(total_ticks):
        # Subsurface runs every 4 ticks (when tick % 4 == 1)
        if tick % 4 == 1:
            profiler.profile_subsurface_tick(state)
            subsurface_count += 1

            if subsurface_count % 50 == 0:
                progress = (subsurface_count / num_subsurface_ticks) * 100
                print(f"    Progress: {progress:.0f}% ({subsurface_count}/{num_subsurface_ticks} subsurface ticks)", end='\r')

    print(f"    Progress: 100% ({num_subsurface_ticks}/{num_subsurface_ticks} subsurface ticks)")
    print("  ✅ Profiling complete!")

    return profiler


if __name__ == "__main__":
    import sys

    num_ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    profiler = run_subsurface_profile(num_ticks)
    profiler.print_report()
