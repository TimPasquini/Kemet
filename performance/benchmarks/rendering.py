#!/usr/bin/env python3
"""
Rendering performance benchmark for Kemet.

Measures frame rendering performance with component-level timing breakdown.
Tests different zoom levels and rendering strategies (cached vs fallback).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from typing import List, Dict, Tuple
from dataclasses import dataclass, field
from statistics import mean, median, stdev
import argparse

try:
    import pygame
except ImportError:
    print("ERROR: pygame-ce is required")
    print("Install with: pip install pygame-ce")
    sys.exit(1)

from game_state import build_initial_state, GameState
from core.camera import Camera
from interface.tools import get_toolbar
from interface.ui_state import get_ui_state
from core.config import GRID_WIDTH, GRID_HEIGHT
from render.config import VIRTUAL_WIDTH, VIRTUAL_HEIGHT, CELL_SIZE, COLOR_BG_DARK
from render import (
    render_static_background,
    render_map_viewport,
    render_night_overlay,
    render_hud,
    render_inventory,
    render_soil_profile,
    render_toolbar,
    render_event_log,
)
from render.map import redraw_background_rect
from render.player_renderer import render_player
from render.minimap import render_minimap
from performance.benchmarks.utils import (
    Timer,
    format_time_ms,
    format_time_s,
    print_section_header,
    print_metric,
    print_progress,
    print_progress_complete,
)


@dataclass
class RenderingMetrics:
    """Collects rendering performance measurements."""

    frame_times: List[float] = field(default_factory=list)
    component_times: Dict[str, List[float]] = field(default_factory=dict)
    visible_cells: List[int] = field(default_factory=list)
    zoom_levels: List[float] = field(default_factory=list)

    def record_frame(self, frame_time: float, zoom: float, visible: int):
        """Record a complete frame timing."""
        self.frame_times.append(frame_time)
        self.zoom_levels.append(zoom)
        self.visible_cells.append(visible)

    def record_component(self, component: str, duration: float):
        """Record a component timing."""
        if component not in self.component_times:
            self.component_times[component] = []
        self.component_times[component].append(duration)

    def get_avg_fps(self) -> float:
        """Calculate average FPS."""
        if not self.frame_times:
            return 0.0
        return 1.0 / mean(self.frame_times)

    def print_report(self, zoom_test: bool = False):
        """Print comprehensive rendering performance report."""
        if not self.frame_times:
            print("No frames rendered")
            return

        # Overall metrics
        print_section_header("KEMET RENDERING PERFORMANCE REPORT")
        print_section_header("OVERALL PERFORMANCE", width=80)

        mean_time = mean(self.frame_times)
        median_time = median(self.frame_times)
        std_time = stdev(self.frame_times) if len(self.frame_times) > 1 else 0.0
        min_time = min(self.frame_times)
        max_time = max(self.frame_times)

        target_frame_time = 1.0 / 60.0  # 16.67ms for 60 FPS
        frames_under_target = sum(1 for t in self.frame_times if t <= target_frame_time)
        pct_under_target = (frames_under_target / len(self.frame_times)) * 100

        print_metric("Total Frames Rendered:", str(len(self.frame_times)))
        print_metric("Average FPS:", f"{self.get_avg_fps():.1f}")
        print_metric("Mean Frame Time:", format_time_ms(mean_time))
        print_metric("Median Frame Time:", format_time_ms(median_time))
        print_metric("Std Dev:", format_time_ms(std_time))
        print_metric("Min Frame Time:", format_time_ms(min_time))
        print_metric("Max Frame Time:", format_time_ms(max_time))
        print_metric("Frames Under 16.67ms:", f"{frames_under_target} ({pct_under_target:.1f}%)")

        # Component breakdown
        if self.component_times:
            print_section_header("COMPONENT BREAKDOWN (average times)", width=80)

            # Calculate total component time (for percentages)
            total_component_time = sum(mean(times) for times in self.component_times.values())

            # Sort by average time (descending)
            sorted_components = sorted(
                self.component_times.items(),
                key=lambda x: mean(x[1]),
                reverse=True
            )

            for component, times in sorted_components:
                avg_time = mean(times)
                pct = (avg_time / total_component_time * 100) if total_component_time > 0 else 0
                print_metric(f"{component}:", f"{format_time_ms(avg_time)}  ({pct:.1f}%)")

        # Zoom level analysis
        if zoom_test and self.zoom_levels:
            print_section_header("ZOOM LEVEL ANALYSIS", width=80)

            unique_zooms = sorted(set(self.zoom_levels))
            for zoom in unique_zooms:
                # Get frame times for this zoom level
                zoom_frames = [t for t, z in zip(self.frame_times, self.zoom_levels) if z == zoom]
                zoom_cells = [c for c, z in zip(self.visible_cells, self.zoom_levels) if z == zoom]

                if zoom_frames:
                    zoom_fps = 1.0 / mean(zoom_frames)
                    avg_cells = int(mean(zoom_cells))
                    print_metric(f"Zoom {zoom:.1f}×:",
                                f"{zoom_fps:.1f} FPS, {format_time_ms(mean(zoom_frames))}/frame, {avg_cells} visible cells")


def render_frame_profiled(
    virtual_screen: pygame.Surface,
    map_surface: pygame.Surface,
    font,
    state: GameState,
    camera: Camera,
    cell_size: int,
    elevation_range: Tuple[float, float],
    player_world_pos: Tuple[float, float],
    toolbar,
    ui_state,
    background_surface: pygame.Surface,
    metrics: RenderingMetrics,
) -> float:
    """Render one frame with component-level timing.

    Mirrors pygame_runner.py's render_to_virtual_screen() but adds timing instrumentation.

    Returns total frame time in seconds.
    """
    frame_start = time.perf_counter()

    # Fill background
    virtual_screen.fill(COLOR_BG_DARK)

    # 1. Map viewport
    with Timer() as t:
        scaled_cell_size = int(cell_size * camera.zoom)
        render_map_viewport(
            map_surface, font, state, camera, scaled_cell_size,
            elevation_range, background_surface
        )
    metrics.record_component('map_viewport', t.elapsed)

    # 2. Player + interaction highlights
    with Timer() as t:
        # Interaction highlights already rendered in render_map_viewport
        render_player(map_surface, state, camera, player_world_pos, scaled_cell_size)
        render_night_overlay(map_surface, state.heat)
    metrics.record_component('player_overlays', t.elapsed)

    # Blit map to virtual screen
    with Timer() as t:
        virtual_screen.blit(map_surface, ui_state.map_rect.topleft)
    metrics.record_component('map_blit', t.elapsed)

    # 3. Minimap
    with Timer() as t:
        sidebar_x = ui_state.sidebar_rect.x
        y_offset = 12
        col1_x = sidebar_x + 12
        minimap_height = 100
        minimap_rect = pygame.Rect(col1_x, y_offset, 130, minimap_height)
        render_minimap(virtual_screen, state, camera, minimap_rect)
    metrics.record_component('minimap', t.elapsed)

    # 4. HUD panels
    with Timer() as t:
        hud_bottom = render_hud(virtual_screen, font, state, col1_x, y_offset + minimap_height + 10)
        render_inventory(virtual_screen, font, state, col1_x, hud_bottom)
    metrics.record_component('hud_panels', t.elapsed)

    # 5. Soil profile
    with Timer() as t:
        col2_x = sidebar_x + 160
        soil_y = y_offset + 22
        soil_height = ui_state.log_panel_rect.y - soil_y - 12
        profile_sub_pos = state.target_cell if state.target_cell else state.player_state.position
        sx, sy = profile_sub_pos
        profile_water = state.water_grid[sx, sy]
        render_soil_profile(virtual_screen, font, state, sx, sy, (col2_x, soil_y),
                           160, soil_height, profile_water)  # PROFILE_WIDTH = 160
    metrics.record_component('soil_profile', t.elapsed)

    # 6. Toolbar
    with Timer() as t:
        render_toolbar(virtual_screen, font, toolbar, ui_state.toolbar_rect.topleft,
                      ui_state.toolbar_rect.width, 60, ui_state)  # TOOLBAR_HEIGHT = 60
    metrics.record_component('toolbar', t.elapsed)

    # 7. Event log
    with Timer() as t:
        log_x, log_y = 12, ui_state.log_panel_rect.y + 8
        render_event_log(virtual_screen, font, state, (log_x, log_y),
                        ui_state.log_panel_rect.height, ui_state.log_scroll_offset)
    metrics.record_component('event_log', t.elapsed)

    frame_time = time.perf_counter() - frame_start
    return frame_time


def run_rendering_benchmark(
    num_frames: int = 300,
    zoom_test: bool = False,
    zoom_levels: List[float] = None,
    fallback: bool = False,
) -> RenderingMetrics:
    """Run rendering benchmark with optional zoom testing.

    Args:
        num_frames: Total number of frames to render
        zoom_test: Test at multiple zoom levels
        zoom_levels: Custom zoom levels (default: [0.5, 1.0, 1.5, 2.0, 3.0])
        fallback: Use fallback rendering (no background cache)

    Returns:
        RenderingMetrics with all collected data
    """
    print("\n🎨 Benchmarking rendering performance...")
    print(f"  Frames to render: {num_frames}")
    print(f"  Zoom test: {'Yes' if zoom_test else 'No'}")
    print(f"  Fallback mode: {'Yes (no cache)' if fallback else 'No (cached background)'}")

    # Initialize pygame with hidden window
    pygame.init()
    screen = pygame.display.set_mode((VIRTUAL_WIDTH, VIRTUAL_HEIGHT), pygame.HIDDEN)
    font = pygame.font.Font(None, 24)  # FONT_SIZE = 24

    # Create virtual screen and map surface
    virtual_screen = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    # Build game state
    print("  Initializing game state...")
    state = build_initial_state()

    # Generate static background (unless fallback mode)
    print(f"  {'Skipping' if fallback else 'Generating'} static background...")
    background_surface = None if fallback else render_static_background(state, font)

    # Setup camera, toolbar, UI
    toolbar = get_toolbar()
    ui_state = get_ui_state()
    camera = Camera()
    camera.set_world_bounds(GRID_WIDTH, GRID_HEIGHT, CELL_SIZE)
    camera.set_viewport_size(ui_state.map_rect.width, ui_state.map_rect.height)

    # Pre-allocate map surface
    map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))

    # Center camera on player
    player_px = state.player_state.smooth_x * CELL_SIZE
    player_py = state.player_state.smooth_y * CELL_SIZE
    camera.center_on(player_px, player_py)

    # Get elevation range
    elevation_range = state.get_elevation_range()

    # Metrics
    metrics = RenderingMetrics()

    # Zoom levels to test
    # NOTE: Lower zoom = more cells visible = more demanding
    # 0.25 is extremely zoomed out (worst case), 3.0 is zoomed in (best case)
    if zoom_test:
        zoom_levels = zoom_levels or [0.25, 0.5, 1.0, 1.5, 2.0, 3.0]  # Include extreme zoom-out
    else:
        zoom_levels = [1.0]

    print(f"  Testing {len(zoom_levels)} zoom level(s)...")

    # Render frames
    for zoom in zoom_levels:
        camera.set_zoom(zoom)
        frames_per_zoom = num_frames // len(zoom_levels)

        print(f"\n  Rendering at zoom {zoom:.1f}×...")

        for frame in range(frames_per_zoom):
            # Get visible cell range
            start_x, start_y, end_x, end_y = camera.get_visible_cell_range()
            visible_count = (end_x - start_x) * (end_y - start_y)

            # Update player position (smooth)
            player_px = state.player_state.smooth_x * CELL_SIZE
            player_py = state.player_state.smooth_y * CELL_SIZE

            # Render frame with timing
            frame_time = render_frame_profiled(
                virtual_screen, map_surface, font, state, camera,
                CELL_SIZE, elevation_range, (player_px, player_py),
                toolbar, ui_state, background_surface, metrics
            )

            metrics.record_frame(frame_time, zoom, visible_count)

            # Progress
            if frame % 50 == 0:
                print_progress(frame, frames_per_zoom, f"Zoom {zoom:.1f}×")

        print_progress_complete(frames_per_zoom, f"Zoom {zoom:.1f}×")

    pygame.quit()
    print("\n  ✅ Benchmark complete!")

    return metrics


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark rendering performance for Kemet"
    )
    parser.add_argument(
        "--num-frames", type=int, default=300,
        help="Number of frames to render (default: 300)"
    )
    parser.add_argument(
        "--zoom-test", action="store_true",
        help="Test at multiple zoom levels (0.5×, 1.0×, 1.5×, 2.0×, 3.0×)"
    )
    parser.add_argument(
        "--fallback", action="store_true",
        help="Use fallback rendering (no background cache)"
    )
    parser.add_argument(
        "--zoom-levels", type=str,
        help="Custom zoom levels (comma-separated, e.g., '0.5,1.0,2.0')"
    )

    args = parser.parse_args()

    # Parse custom zoom levels if provided
    zoom_levels = None
    if args.zoom_levels:
        zoom_levels = [float(z.strip()) for z in args.zoom_levels.split(',')]
        args.zoom_test = True

    # Run benchmark
    metrics = run_rendering_benchmark(
        num_frames=args.num_frames,
        zoom_test=args.zoom_test,
        zoom_levels=zoom_levels,
        fallback=args.fallback,
    )

    # Print report
    metrics.print_report(zoom_test=args.zoom_test)


if __name__ == "__main__":
    main()
