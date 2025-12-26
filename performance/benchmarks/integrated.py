#!/usr/bin/env python3
"""
Integrated simulation + rendering benchmark for Kemet.

Measures real-world gameplay performance by combining simulation ticks
with frame rendering, similar to actual game loop.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
import argparse
from typing import Tuple

import pygame

from game_state import build_initial_state, GameState
from main import simulate_tick
from core.camera import Camera
from interface.tools import get_toolbar
from interface.ui_state import get_ui_state
from core.config import GRID_WIDTH, GRID_HEIGHT, TICK_INTERVAL
from render.config import VIRTUAL_WIDTH, VIRTUAL_HEIGHT, CELL_SIZE
from render import render_static_background
from performance.benchmarks.rendering import RenderingMetrics, render_frame_profiled
from performance.benchmarks.utils import (
    format_time_ms,
    format_time_s,
    print_section_header,
    print_metric,
    print_progress,
    print_progress_complete,
)


class IntegratedMetrics:
    """Metrics for integrated simulation + rendering."""

    def __init__(self):
        self.sim_times = []
        self.render_times = []
        self.combined_times = []

    def record(self, sim_time: float, render_time: float):
        """Record timing for one tick+render cycle."""
        self.sim_times.append(sim_time)
        self.render_times.append(render_time)
        self.combined_times.append(sim_time + render_time)

    def get_avg_tps(self) -> float:
        """Average ticks per second (simulation only)."""
        if not self.sim_times:
            return 0.0
        from statistics import mean
        return 1.0 / mean(self.sim_times)

    def get_avg_fps(self) -> float:
        """Average frames per second (combined sim+render)."""
        if not self.combined_times:
            return 0.0
        from statistics import mean
        return 1.0 / mean(self.combined_times)

    def print_report(self):
        """Print integrated performance report."""
        if not self.combined_times:
            print("No data collected")
            return

        from statistics import mean, median, stdev

        # Overall metrics
        print_section_header("INTEGRATED PERFORMANCE REPORT")
        print_section_header("OVERALL METRICS", width=80)

        print_metric("Total Ticks:", str(len(self.sim_times)))
        print_metric("Frames Rendered:", str(len(self.render_times)))
        print_metric("Average TPS (sim):", f"{self.get_avg_tps():.1f}")
        print_metric("Average FPS (combined):", f"{self.get_avg_fps():.1f}")

        # Simulation timing
        print_section_header("SIMULATION TIMING", width=80)
        sim_mean = mean(self.sim_times)
        sim_median = median(self.sim_times)
        sim_std = stdev(self.sim_times) if len(self.sim_times) > 1 else 0.0

        print_metric("Mean:", format_time_ms(sim_mean))
        print_metric("Median:", format_time_ms(sim_median))
        print_metric("Std Dev:", format_time_ms(sim_std))
        print_metric("Min:", format_time_ms(min(self.sim_times)))
        print_metric("Max:", format_time_ms(max(self.sim_times)))

        # Rendering timing
        print_section_header("RENDERING TIMING", width=80)
        render_mean = mean(self.render_times)
        render_median = median(self.render_times)
        render_std = stdev(self.render_times) if len(self.render_times) > 1 else 0.0

        print_metric("Mean:", format_time_ms(render_mean))
        print_metric("Median:", format_time_ms(render_median))
        print_metric("Std Dev:", format_time_ms(render_std))
        print_metric("Min:", format_time_ms(min(self.render_times)))
        print_metric("Max:", format_time_ms(max(self.render_times)))

        # Combined timing
        print_section_header("COMBINED TICK + RENDER", width=80)
        combined_mean = mean(self.combined_times)
        combined_median = median(self.combined_times)

        sim_pct = (sim_mean / combined_mean * 100) if combined_mean > 0 else 0
        render_pct = (render_mean / combined_mean * 100) if combined_mean > 0 else 0

        print_metric("Mean Total:", format_time_ms(combined_mean))
        print_metric("Median Total:", format_time_ms(combined_median))
        print_metric("Simulation %:", f"{sim_pct:.1f}%")
        print_metric("Rendering %:", f"{render_pct:.1f}%")

        # Performance target analysis
        target_frame_time = 1.0 / 60.0  # 16.67ms
        frames_under_target = sum(1 for t in self.combined_times if t <= target_frame_time)
        pct_under_target = (frames_under_target / len(self.combined_times)) * 100

        print_metric("Ticks under 16.67ms:", f"{frames_under_target} ({pct_under_target:.1f}%)")


def run_integrated_benchmark(
    num_ticks: int = 500,
    render_every_tick: bool = True,
) -> IntegratedMetrics:
    """Run integrated simulation + rendering benchmark.

    Args:
        num_ticks: Number of simulation ticks to run
        render_every_tick: Render a frame for every tick (default: True)

    Returns:
        IntegratedMetrics with collected data
    """
    print("\n🎮 Benchmarking integrated simulation + rendering...")
    print(f"  Ticks to run: {num_ticks}")
    print(f"  Render mode: {'Every tick' if render_every_tick else 'Disabled'}")

    # Initialize pygame with hidden window
    pygame.init()
    screen = pygame.display.set_mode((VIRTUAL_WIDTH, VIRTUAL_HEIGHT), pygame.HIDDEN)
    font = pygame.font.Font(None, 24)

    # Create surfaces
    virtual_screen = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    # Build game state
    print("  Initializing game state...")
    state = build_initial_state()

    if render_every_tick:
        print("  Generating static background...")
        background_surface = render_static_background(state, font)

        # Setup camera, toolbar, UI
        toolbar = get_toolbar()
        ui_state = get_ui_state()
        camera = Camera()
        camera.set_world_bounds(GRID_WIDTH, GRID_HEIGHT, CELL_SIZE)
        camera.set_viewport_size(ui_state.map_rect.width, ui_state.map_rect.height)
        map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))

        # Center camera on player
        player_px = state.player_state.smooth_x * CELL_SIZE
        player_py = state.player_state.smooth_y * CELL_SIZE
        camera.center_on(player_px, player_py)

        elevation_range = state.get_elevation_range()
    else:
        background_surface = None

    metrics = IntegratedMetrics()

    print(f"  Running {num_ticks} ticks...")

    for tick in range(num_ticks):
        # Simulation tick
        sim_start = time.perf_counter()
        simulate_tick(state)
        sim_time = time.perf_counter() - sim_start

        # Rendering (if enabled)
        if render_every_tick:
            render_start = time.perf_counter()

            # Update player position
            player_px = state.player_state.smooth_x * CELL_SIZE
            player_py = state.player_state.smooth_y * CELL_SIZE

            # Render frame (simplified - no full metrics tracking)
            render_frame_profiled(
                virtual_screen, map_surface, font, state, camera,
                CELL_SIZE, elevation_range, (player_px, player_py),
                toolbar, ui_state, background_surface,
                RenderingMetrics()  # Dummy metrics, we don't need component breakdown
            )

            render_time = time.perf_counter() - render_start
        else:
            render_time = 0.0

        metrics.record(sim_time, render_time)

        # Progress
        if tick % 50 == 0:
            print_progress(tick, num_ticks)

    print_progress_complete(num_ticks)

    pygame.quit()
    print("  ✅ Benchmark complete!")

    return metrics


def compare_headless_vs_rendered(num_ticks: int = 500):
    """Compare headless simulation vs with rendering.

    Args:
        num_ticks: Number of ticks to run for each test
    """
    print("\n📊 Comparing headless vs rendered performance...")

    # Run headless
    print("\n--- Running headless simulation ---")
    from performance.benchmarks.simulation import run_benchmark
    from statistics import mean

    print("  (This will take a few minutes...)")
    headless_start = time.perf_counter()

    # Capture headless metrics (suppress output temporarily)
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    headless_metrics = run_benchmark(num_ticks, profile_hotspots=False)
    sys.stdout = old_stdout

    headless_time = time.perf_counter() - headless_start
    headless_tps = num_ticks / headless_time

    print(f"  ✅ Headless complete: {headless_tps:.1f} TPS, {format_time_s(headless_time)} total")

    # Run with rendering
    print("\n--- Running with rendering ---")
    rendered_metrics = run_integrated_benchmark(num_ticks, render_every_tick=True)

    # Comparison report
    print("\n" + "="*80)
    print("COMPARISON: HEADLESS VS RENDERED")
    print("="*80)

    print_metric("Headless TPS:", f"{headless_tps:.1f}")
    print_metric("Rendered TPS (sim only):", f"{rendered_metrics.get_avg_tps():.1f}")
    print_metric("Rendered FPS (combined):", f"{rendered_metrics.get_avg_fps():.1f}")

    if headless_tps > 0:
        overhead_pct = ((headless_tps - rendered_metrics.get_avg_tps()) / headless_tps) * 100
        print_metric("Rendering overhead:", f"{overhead_pct:.1f}%")

    sim_mean = mean(rendered_metrics.sim_times) if rendered_metrics.sim_times else 0
    render_mean = mean(rendered_metrics.render_times) if rendered_metrics.render_times else 0

    if sim_mean + render_mean > 0:
        sim_pct = (sim_mean / (sim_mean + render_mean)) * 100
        render_pct = (render_mean / (sim_mean + render_mean)) * 100
        print_metric("Time in simulation:", f"{sim_pct:.1f}%")
        print_metric("Time in rendering:", f"{render_pct:.1f}%")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Integrated simulation + rendering benchmark for Kemet"
    )
    parser.add_argument(
        "--num-ticks", type=int, default=500,
        help="Number of simulation ticks to run (default: 500)"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run simulation only (no rendering)"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Compare headless vs rendered performance"
    )

    args = parser.parse_args()

    if args.compare:
        compare_headless_vs_rendered(args.num_ticks)
    else:
        metrics = run_integrated_benchmark(
            num_ticks=args.num_ticks,
            render_every_tick=not args.headless,
        )
        metrics.print_report()


if __name__ == "__main__":
    main()
