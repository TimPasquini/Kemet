#!/usr/bin/env python3
"""
Detailed profiling for rendering operations.

Provides hierarchical breakdown of rendering performance, similar to subsurface_profiler.py
but for the rendering pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from typing import Dict, List
from statistics import mean, median
from dataclasses import dataclass, field

import pygame

from game_state import build_initial_state, GameState
from camera import Camera
from tools import get_toolbar
from ui_state import get_ui_state
from config import GRID_WIDTH, GRID_HEIGHT
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
from render.player_renderer import render_player
from render.minimap import render_minimap


@dataclass
class FunctionProfile:
    """Profile data for a rendering function."""
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


class RenderingProfiler:
    """Detailed profiler for rendering operations."""

    def __init__(self):
        self.profiles: Dict[str, FunctionProfile] = {}
        self.total_frame_time: float = 0.0

    def get_profile(self, name: str) -> FunctionProfile:
        """Get or create a profile for a function."""
        if name not in self.profiles:
            self.profiles[name] = FunctionProfile(name)
        return self.profiles[name]

    def profile_frame(
        self,
        virtual_screen: pygame.Surface,
        map_surface: pygame.Surface,
        font,
        state: GameState,
        camera: Camera,
        cell_size: int,
        elevation_range,
        player_world_pos,
        toolbar,
        ui_state,
        background_surface: pygame.Surface,
    ) -> float:
        """Profile single frame with hierarchical breakdown."""
        frame_start = time.perf_counter()

        # 0. Background fill
        fill_start = time.perf_counter()
        virtual_screen.fill(COLOR_BG_DARK)
        self.get_profile("0_background_fill").record(time.perf_counter() - fill_start)

        # 1. Map viewport (with detailed sub-profiling)
        map_start = time.perf_counter()
        scaled_cell_size = int(cell_size * camera.zoom)

        # Note: We can't easily break down render_map_viewport without modifying it,
        # so we profile it as a whole here
        render_map_viewport(
            map_surface, font, state, camera, scaled_cell_size,
            elevation_range, background_surface
        )
        self.get_profile("1_map_viewport").record(time.perf_counter() - map_start)

        # 2. Player + overlays
        player_start = time.perf_counter()
        render_player(map_surface, state, camera, player_world_pos, scaled_cell_size)
        render_night_overlay(map_surface, state.heat)
        self.get_profile("2_player_overlays").record(time.perf_counter() - player_start)

        # 3. Map blit
        blit_start = time.perf_counter()
        virtual_screen.blit(map_surface, ui_state.map_rect.topleft)
        self.get_profile("3_map_blit").record(time.perf_counter() - blit_start)

        # 4. Minimap
        minimap_start = time.perf_counter()
        sidebar_x = ui_state.sidebar_rect.x
        y_offset = 12
        col1_x = sidebar_x + 12
        minimap_height = 100
        minimap_rect = pygame.Rect(col1_x, y_offset, 130, minimap_height)
        render_minimap(virtual_screen, state, camera, minimap_rect)
        self.get_profile("4_minimap").record(time.perf_counter() - minimap_start)

        # 5. HUD panels
        hud_start = time.perf_counter()
        hud_bottom = render_hud(virtual_screen, font, state, col1_x, y_offset + minimap_height + 10)
        render_inventory(virtual_screen, font, state, col1_x, hud_bottom)
        self.get_profile("5_hud_panels").record(time.perf_counter() - hud_start)

        # 6. Soil profile
        soil_start = time.perf_counter()
        col2_x = sidebar_x + 160
        soil_y = y_offset + 22
        soil_height = ui_state.log_panel_rect.y - soil_y - 12
        profile_sub_pos = state.target_cell if state.target_cell else state.player_state.position
        sx, sy = profile_sub_pos
        profile_water = state.water_grid[sx, sy]
        render_soil_profile(virtual_screen, font, state, sx, sy, (col2_x, soil_y),
                           160, soil_height, profile_water)
        self.get_profile("6_soil_profile").record(time.perf_counter() - soil_start)

        # 7. Toolbar
        toolbar_start = time.perf_counter()
        render_toolbar(virtual_screen, font, toolbar, ui_state.toolbar_rect.topleft,
                      ui_state.toolbar_rect.width, 60, ui_state)
        self.get_profile("7_toolbar").record(time.perf_counter() - toolbar_start)

        # 8. Event log
        log_start = time.perf_counter()
        log_x, log_y = 12, ui_state.log_panel_rect.y + 8
        render_event_log(virtual_screen, font, state, (log_x, log_y),
                        ui_state.log_panel_rect.height, ui_state.log_scroll_offset)
        self.get_profile("8_event_log").record(time.perf_counter() - log_start)

        frame_time = time.perf_counter() - frame_start
        self.total_frame_time += frame_time
        return frame_time

    def print_report(self):
        """Print detailed profiling report."""
        print("\n" + "="*80)
        print("RENDERING DETAILED PROFILE")
        print("="*80)

        # Sort by total time (descending - show hotspots first)
        sorted_profiles = sorted(
            self.profiles.values(),
            key=lambda p: p.total_time,
            reverse=True
        )

        # Column headers
        print(f"{'Function':<40} {'Calls':<8} {'Total (ms)':<12} {'Avg (ms)':<12} {'% Time':<8}")
        print("-"*80)

        # Data rows
        for profile in sorted_profiles:
            print(f"{profile.name:<40} {profile.call_count:<8} "
                  f"{profile.total_time*1000:<12.2f} "
                  f"{profile.avg_time_ms():<12.2f} "
                  f"{profile.pct_of_total(self.total_frame_time):<8.1f}")

        # Footer
        print("-"*80)
        print(f"{'TOTAL FRAME TIME':<40} {'':<8} "
              f"{self.total_frame_time*1000:<12.2f} {'':<12} {'100.0':<8}")
        print("="*80)


def run_rendering_profile(num_frames: int = 300) -> RenderingProfiler:
    """
    Run a focused rendering profiling session.

    Args:
        num_frames: Number of frames to profile

    Returns:
        RenderingProfiler with collected data
    """
    print(f"\n🔬 Profiling rendering ({num_frames} frames)...")
    print("  Initializing game state...")

    # Initialize pygame with hidden window
    pygame.init()
    screen = pygame.display.set_mode((VIRTUAL_WIDTH, VIRTUAL_HEIGHT), pygame.HIDDEN)
    font = pygame.font.Font(None, 24)

    virtual_screen = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    # Build game state
    state = build_initial_state()
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

    profiler = RenderingProfiler()

    print(f"  Rendering {num_frames} frames...")

    for frame in range(num_frames):
        player_px = state.player_state.smooth_x * CELL_SIZE
        player_py = state.player_state.smooth_y * CELL_SIZE

        profiler.profile_frame(
            virtual_screen, map_surface, font, state, camera,
            CELL_SIZE, elevation_range, (player_px, player_py),
            toolbar, ui_state, background_surface
        )

        if frame % 50 == 0:
            progress = (frame / num_frames) * 100
            print(f"    Progress: {progress:.0f}% ({frame}/{num_frames})", end='\r')

    print(f"    Progress: 100% ({num_frames}/{num_frames})")
    print("  ✅ Profiling complete!")

    pygame.quit()

    return profiler


if __name__ == "__main__":
    import sys

    num_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    profiler = run_rendering_profile(num_frames)
    profiler.print_report()
