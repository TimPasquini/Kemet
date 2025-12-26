#!/usr/bin/env python3
"""
Performance benchmarking script for Kemet simulation.

Runs the simulation headless (no rendering) to measure pure simulation performance.
Profiles FPS, memory usage, tick times, and identifies hot code paths.
"""
from __future__ import annotations

import cProfile
import pstats
import io
import time
import tracemalloc
from typing import Dict, List, Tuple
from statistics import mean, median, stdev

import numpy as np

from game_state import build_initial_state
from main import simulate_tick, end_day
from core.config import TICK_INTERVAL, GRID_WIDTH, GRID_HEIGHT


class PerformanceMetrics:
    """Tracks performance metrics during simulation."""

    def __init__(self):
        self.tick_times: List[float] = []
        self.system_times: Dict[str, List[float]] = {
            'surface_flow': [],
            'surface_seepage': [],
            'subsurface': [],
            'evaporation': [],
            'atmosphere': [],
            'wind_exposure': [],
            'structures': [],
            'total_tick': [],
        }
        self.memory_snapshots: List[int] = []  # Bytes
        self.start_time: float = 0
        self.end_time: float = 0

    def start_benchmark(self):
        """Start timing the benchmark."""
        self.start_time = time.perf_counter()

    def end_benchmark(self):
        """End timing the benchmark."""
        self.end_time = time.perf_counter()

    def record_tick_time(self, tick_time: float):
        """Record the time for a single simulation tick."""
        self.tick_times.append(tick_time)

    def record_system_time(self, system: str, duration: float):
        """Record timing for a specific subsystem."""
        if system in self.system_times:
            self.system_times[system].append(duration)

    def record_memory(self):
        """Record current memory usage."""
        current, peak = tracemalloc.get_traced_memory()
        self.memory_snapshots.append(current)

    def get_total_time(self) -> float:
        """Get total benchmark duration."""
        return self.end_time - self.start_time

    def print_report(self):
        """Print a comprehensive performance report."""
        print("\n" + "="*80)
        print("KEMET PERFORMANCE BASELINE REPORT")
        print(f"Grid Size: {GRID_WIDTH}×{GRID_HEIGHT} cells")
        print("="*80)

        # Overall timing
        total_time = self.get_total_time()
        total_ticks = len(self.tick_times)
        print(f"\n📊 OVERALL PERFORMANCE")
        print(f"  Total Runtime:      {total_time:.2f}s")
        print(f"  Total Ticks:        {total_ticks}")
        print(f"  Average TPS:        {total_ticks / total_time:.1f} ticks/sec")

        # Tick timing statistics
        if self.tick_times:
            print(f"\n⏱️  TICK TIMING")
            print(f"  Mean:               {mean(self.tick_times)*1000:.2f}ms")
            print(f"  Median:             {median(self.tick_times)*1000:.2f}ms")
            if len(self.tick_times) > 1:
                print(f"  Std Dev:            {stdev(self.tick_times)*1000:.2f}ms")
            print(f"  Min:                {min(self.tick_times)*1000:.2f}ms")
            print(f"  Max:                {max(self.tick_times)*1000:.2f}ms")

            # FPS equivalent (if we rendered every tick)
            avg_tick = mean(self.tick_times)
            equiv_fps = 1.0 / avg_tick if avg_tick > 0 else 0
            print(f"  Equiv FPS:          {equiv_fps:.1f} (if rendering each tick)")

        # System breakdown
        print(f"\n🔧 SYSTEM BREAKDOWN (average times)")
        system_order = [
            ('total_tick', 'Total Tick'),
            ('surface_flow', 'Surface Flow'),
            ('surface_seepage', 'Surface Seepage'),
            ('subsurface', 'Subsurface'),
            ('evaporation', 'Evaporation'),
            ('atmosphere', 'Atmosphere'),
            ('wind_exposure', 'Wind Exposure'),
            ('structures', 'Structures'),
        ]

        for system_key, system_name in system_order:
            times = self.system_times[system_key]
            if times:
                avg_time = mean(times) * 1000
                pct = (mean(times) / mean(self.tick_times) * 100) if self.tick_times else 0
                print(f"  {system_name:20s} {avg_time:6.2f}ms  ({pct:5.1f}%)")

        # Memory statistics
        if self.memory_snapshots:
            print(f"\n💾 MEMORY USAGE")
            print(f"  Mean:               {mean(self.memory_snapshots) / 1024 / 1024:.1f} MB")
            print(f"  Peak:               {max(self.memory_snapshots) / 1024 / 1024:.1f} MB")
            print(f"  Min:                {min(self.memory_snapshots) / 1024 / 1024:.1f} MB")

        print("\n" + "="*80)


def simulate_tick_profiled(state, metrics: PerformanceMetrics) -> None:
    """Run one simulation tick with detailed timing."""
    tick_start = time.perf_counter()

    # Weather and structures
    struct_start = time.perf_counter()
    weather_messages = state.weather.tick()
    state.messages.extend(weather_messages)
    from structures import tick_structures
    tick_structures(state, state.heat)
    metrics.record_system_time('structures', time.perf_counter() - struct_start)

    tick = state.weather.turn_in_day

    # Surface flow (every 2 ticks)
    if tick % 2 == 0:
        flow_start = time.perf_counter()
        from simulation.surface import simulate_surface_flow
        simulate_surface_flow(state)
        metrics.record_system_time('surface_flow', time.perf_counter() - flow_start)

    # Surface seepage (every 2 ticks, offset)
    if tick % 2 == 1:
        seep_start = time.perf_counter()
        from simulation.surface import simulate_surface_seepage
        simulate_surface_seepage(state)

        # Moisture history update
        subsurface_total = np.sum(state.subsurface_water_grid, axis=0)
        current_moisture_grid = state.water_grid + subsurface_total

        if state.moisture_grid is None:
            state.moisture_grid = current_moisture_grid.astype(float)
        else:
            from core.config import MOISTURE_EMA_ALPHA
            state.moisture_grid = (1 - MOISTURE_EMA_ALPHA) * state.moisture_grid + MOISTURE_EMA_ALPHA * current_moisture_grid

        metrics.record_system_time('surface_seepage', time.perf_counter() - seep_start)

    # Subsurface (every 4 ticks)
    if tick % 4 == 1:
        sub_start = time.perf_counter()
        from simulation.subsurface_vectorized import simulate_subsurface_tick_vectorized
        simulate_subsurface_tick_vectorized(state)
        metrics.record_system_time('subsurface', time.perf_counter() - sub_start)

    # Evaporation (every tick)
    evap_start = time.perf_counter()
    from simulation.subsurface import apply_surface_evaporation
    apply_surface_evaporation(state)
    metrics.record_system_time('evaporation', time.perf_counter() - evap_start)

    # Atmosphere (every 2 ticks)
    if tick % 2 == 0:
        if state.humidity_grid is not None and state.wind_grid is not None:
            atmo_start = time.perf_counter()
            from simulation.atmosphere import simulate_atmosphere_tick_vectorized
            simulate_atmosphere_tick_vectorized(state)
            metrics.record_system_time('atmosphere', time.perf_counter() - atmo_start)

    # Wind exposure (every 10 ticks)
    if tick % 10 == 0:
        wind_start = time.perf_counter()
        from simulation.erosion import accumulate_wind_exposure
        accumulate_wind_exposure(state)
        metrics.record_system_time('wind_exposure', time.perf_counter() - wind_start)

    tick_time = time.perf_counter() - tick_start
    metrics.record_tick_time(tick_time)
    metrics.record_system_time('total_tick', tick_time)


def run_benchmark(num_ticks: int = 1000, profile_hotspots: bool = True) -> PerformanceMetrics:
    """
    Run a headless simulation benchmark.

    Args:
        num_ticks: Number of simulation ticks to run
        profile_hotspots: If True, run cProfile to identify hot code paths

    Returns:
        PerformanceMetrics object with collected data
    """
    print(f"\n🚀 Starting benchmark: {num_ticks} ticks on {GRID_WIDTH}×{GRID_HEIGHT} grid...")

    # Start memory tracking
    tracemalloc.start()

    # Build initial state
    print("  Initializing game state...")
    state = build_initial_state()

    # Create metrics tracker
    metrics = PerformanceMetrics()

    # Run benchmark
    print(f"  Running {num_ticks} simulation ticks...")
    metrics.start_benchmark()

    if profile_hotspots:
        # Run with cProfile enabled
        profiler = cProfile.Profile()
        profiler.enable()

    for i in range(num_ticks):
        simulate_tick_profiled(state, metrics)

        # Record memory every 100 ticks
        if i % 100 == 0:
            metrics.record_memory()
            if i > 0:
                progress = (i / num_ticks) * 100
                print(f"    Progress: {progress:.0f}% ({i}/{num_ticks} ticks)", end='\r')

    print(f"    Progress: 100% ({num_ticks}/{num_ticks} ticks)")

    if profile_hotspots:
        profiler.disable()

    metrics.end_benchmark()

    # Stop memory tracking
    tracemalloc.stop()

    print("  ✅ Benchmark complete!")

    # Print performance report
    metrics.print_report()

    # Print hotspot analysis
    if profile_hotspots:
        print("\n🔥 HOT CODE PATHS (Top 20 functions by cumulative time)")
        print("="*80)
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
        ps.print_stats(20)

        # Filter output to show only relevant lines
        output = s.getvalue()
        lines = output.split('\n')
        for line in lines[:25]:  # Show first 25 lines (header + top 20)
            if line.strip():
                print(line)

        print("\n🔥 HOT CODE PATHS (Top 20 functions by total time)")
        print("="*80)
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('tottime')
        ps.print_stats(20)

        output = s.getvalue()
        lines = output.split('\n')
        for line in lines[:25]:
            if line.strip():
                print(line)

    return metrics


def compare_grid_sizes():
    """Run benchmarks at different grid sizes for comparison."""
    print("\n" + "="*80)
    print("GRID SIZE COMPARISON BENCHMARK")
    print("="*80)

    # This would require modifying GRID_WIDTH/GRID_HEIGHT
    # For now, just run the current size
    print("\nNote: To test different grid sizes, manually modify config.py")
    print(f"Current grid: {GRID_WIDTH}×{GRID_HEIGHT}")

    run_benchmark(num_ticks=500, profile_hotspots=False)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare_grid_sizes()
    else:
        # Default: run 1000 ticks with profiling
        run_benchmark(num_ticks=1000, profile_hotspots=True)
