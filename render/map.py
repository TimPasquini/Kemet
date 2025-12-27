# render/map.py
"""Map, structure, and player rendering with camera support.

Rendering now supports:
- Grid cell features (biome colors, structures)
- Water visualization
- Interaction range highlights
"""
from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING, Tuple, Optional, List

import pygame
import numpy as np

from world.terrain import BIOME_TYPES
from render.primitives import draw_text
from render.grid_helpers import get_grid_cell_color, get_grid_elevation
from core.config import (
        INTERACTION_RANGE,
    GRID_WIDTH,
    GRID_HEIGHT,
)
from render.config import (
    STRUCTURE_INSET,
    TRENCH_INSET,
    WELLSPRING_RADIUS,
    PLAYER_RADIUS,
    CELL_SIZE,
    COLOR_BG_DARK,
    COLOR_STRUCTURE,
    COLOR_WELLSPRING_STRONG,
    COLOR_WELLSPRING_WEAK,
    COLOR_DEPOT,
    COLOR_TRENCH,
    HIGHLIGHT_COLORS,
)
from core.utils import chebyshev_distance

if TYPE_CHECKING:
    from main import GameState
    from core.camera import Camera
    from interface.tools import Tool
    from interface.ui_state import UIState

# =============================================================================
# Surface Caches (performance optimization)
# =============================================================================
# Cache highlight surfaces by (size, color, alpha) to avoid per-frame surface creation
_HIGHLIGHT_SURFACE_CACHE: dict = {}


def _get_cached_highlight_surface(
    size: int,
    color: Tuple[int, int, int],
    alpha: int,
) -> pygame.Surface:
    """Get a cached highlight surface, creating if needed."""
    key = (size, color, alpha)

    if key not in _HIGHLIGHT_SURFACE_CACHE:
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        surf.fill((*color, alpha))
        _HIGHLIGHT_SURFACE_CACHE[key] = surf

    return _HIGHLIGHT_SURFACE_CACHE[key]


def render_map_viewport(
    surface: pygame.Surface,
    font,
    state: "GameState",
    camera: "Camera",
    scaled_cell_size: int,
    elevation_range: Tuple[float, float],
    background_surface: pygame.Surface = None,
) -> None:
    """Render the visible portion of the world to the map viewport surface.

    Renders at grid cell resolution - each grid cell has its own biome color.

    Args:
        surface: Surface to render to (sized to camera viewport)
        font: Font for text rendering
        state: Game state with grid data and structures
        camera: Camera defining visible region
        scaled_cell_size: Size of grid cell in pixels at current zoom
        elevation_range: (min, max) elevation for color scaling
        background_surface: Pre-rendered static terrain (optional, falls back to per-frame render)
    """
    surface.fill(COLOR_BG_DARK)

    if background_surface is not None:
        # --- 1. Blit the pre-rendered static background ---
        # Determine the source rectangle from the full-world background surface
        # that corresponds to the camera's current view.
        # CRITICAL: Round camera positions to pixel boundaries to prevent sub-pixel
        # misalignment between the scaled background and grid-based overlays (water, etc.)
        src_w = camera.viewport_width / camera.zoom
        src_h = camera.viewport_height / camera.zoom
        source_rect = pygame.Rect(round(camera.world_x), round(camera.world_y), src_w, src_h)

        # Clip the source rectangle to the bounds of the background surface
        # to prevent "subsurface outside surface" errors at the edges.
        source_rect.clamp_ip(background_surface.get_rect())

        # Extract the visible portion and scale it to fit the viewport.
        if source_rect.width > 0 and source_rect.height > 0:
            visible_bg = background_surface.subsurface(source_rect)
            scaled_bg = pygame.transform.scale(visible_bg, surface.get_size())
            surface.blit(scaled_bg, (0, 0))
    else:
        # Fallback: render terrain per-frame (slower but works without background cache)
        _render_terrain_per_frame(surface, state, camera, scaled_cell_size, elevation_range)

    # --- 2. Draw dynamic elements on top of the background ---
    # Draw structures (keyed by grid cell coords, rendered at grid cell position)
    # Use CELL_SIZE directly to match background scaling
    scaled_sub_size = max(1, scaled_cell_size)
    for (grid_x, grid_y), structure in state.structures.items():
        # Check if grid cell is visible
        if not camera.is_cell_visible(grid_x, grid_y):
            continue
        # Get world position for grid cell using camera method
        world_x, world_y = camera.cell_to_world(grid_x, grid_y)
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), scaled_sub_size, scaled_sub_size)
        pygame.draw.rect(surface, COLOR_STRUCTURE, rect.inflate(-2, -2))
        # Draw structure initial centered in grid cell
        if scaled_sub_size >= 8:  # Only draw letter if big enough
            draw_text(surface, font, structure.kind[0].upper(), (rect.x + scaled_sub_size // 3, rect.y + scaled_sub_size // 4))

    # Draw wellsprings - check all visible grid cells
    start_sx, start_sy, end_sx, end_sy = camera.get_visible_cell_range()
    for sy in range(start_sy, end_sy):
        for sx in range(start_sx, end_sx):
            wellspring_output = state.wellspring_grid[sx, sy] if state.wellspring_grid is not None else 0
            if wellspring_output > 0:
                # Get grid cell screen position
                world_x, world_y = camera.cell_to_world(sx, sy)
                vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

                # Draw wellspring circle at cell center
                cell_center_x = int(vp_x + scaled_sub_size // 2)
                cell_center_y = int(vp_y + scaled_sub_size // 2)
                spring_color = COLOR_WELLSPRING_STRONG if wellspring_output / 10 > 0.5 else COLOR_WELLSPRING_WEAK
                radius = max(2, int(WELLSPRING_RADIUS * camera.zoom))
                pygame.draw.circle(surface, spring_color, (cell_center_x, cell_center_y), radius)

    # Render water overlay (dynamic, so drawn on top of static background)
    render_water_overlay(surface, state, camera, scaled_cell_size)


def _render_terrain_per_frame(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    scaled_cell_size: int,
    elevation_range: Tuple[float, float],
) -> None:
    """Fallback terrain rendering - renders each visible grid cell per frame."""
    start_x, start_y, end_x, end_y = camera.get_visible_cell_range()

    for sy in range(start_y, end_y):
        for sx in range(start_x, end_x):
            # Grid-based color computation using array data directly
            color = get_grid_cell_color(state, sx, sy, elevation_range)

            world_x, world_y = camera.cell_to_world(sx, sy)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), scaled_cell_size, scaled_cell_size)
            pygame.draw.rect(surface, color, rect)


def render_water_overlay(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    scaled_cell_size: int,
) -> None:
    """
    Render water using fully vectorized operations for maximum performance.
    Uses the same scaling approach as the background to ensure perfect alignment.
    """
    from render.config import CELL_SIZE

    start_x, start_y, end_x, end_y = camera.get_visible_cell_range()

    # Get visible water region as a single slice
    water_region = state.water_grid[start_x:end_x, start_y:end_y]

    # Quick check if there's any water to render
    if np.max(water_region) <= 2:
        return

    # Create RGBA array at grid resolution (one pixel per cell, like background)
    grid_shape = water_region.shape
    rgba_grid = np.zeros((*grid_shape, 4), dtype=np.uint8)

    # Vectorized water depth classification
    has_water = water_region > 2
    shallow = has_water & (water_region <= 20)
    medium = (water_region > 20) & (water_region <= 50)
    deep = water_region > 50

    # Vectorized color assignment
    rgba_grid[shallow, :3] = [100, 180, 230]
    rgba_grid[medium, :3] = [60, 140, 210]
    rgba_grid[deep, :3] = [40, 100, 180]

    # Vectorized alpha calculation with proper clipping
    rgba_grid[shallow, 3] = np.clip(40 + water_region[shallow] * 3, 0, 255).astype(np.uint8)
    rgba_grid[medium, 3] = np.clip(100 + (water_region[medium] - 20) * 2, 0, 255).astype(np.uint8)
    rgba_grid[deep, 3] = np.clip(160 + (water_region[deep] - 50), 0, 200).astype(np.uint8)

    # PERFORMANCE-OPTIMIZED with alignment preservation:
    # Use adaptive resolution based on zoom level to avoid creating massive surfaces
    # At low zoom (zoomed out), use lower resolution; at high zoom, use full detail
    try:
        # Calculate optimal scale factor based on zoom
        # At zoom >= 1.0: use full CELL_SIZE detail
        # At zoom < 1.0: reduce proportionally (e.g., zoom 0.25 → 12px per cell instead of 48px)
        scale_factor = max(4, int(CELL_SIZE * min(1.0, camera.zoom)))

        # Step 1: Create water at adaptive scale
        pixel_array = rgba_grid.repeat(scale_factor, axis=0).repeat(scale_factor, axis=1)

        # Transpose to (height, width, channels) for pygame
        pixel_array_hwc = np.transpose(pixel_array, (1, 0, 2))

        width_pixels = pixel_array.shape[0]
        height_pixels = pixel_array.shape[1]

        water_surface = pygame.image.frombuffer(
            pixel_array_hwc.tobytes(),
            (width_pixels, height_pixels),
            'RGBA'
        )

        # Step 2: Extract visible region with scale-adjusted coordinates
        # Calculate where the water surface starts in world coordinates
        world_start_x = start_x * CELL_SIZE
        world_start_y = start_y * CELL_SIZE

        # Calculate offset, scaled to our adaptive resolution
        offset_x = int((round(camera.world_x) - world_start_x) * scale_factor / CELL_SIZE)
        offset_y = int((round(camera.world_y) - world_start_y) * scale_factor / CELL_SIZE)

        # Source rect dimensions, scaled to our adaptive resolution
        src_w = int((camera.viewport_width / camera.zoom) * scale_factor / CELL_SIZE)
        src_h = int((camera.viewport_height / camera.zoom) * scale_factor / CELL_SIZE)

        source_rect = pygame.Rect(offset_x, offset_y, src_w, src_h)
        source_rect.clamp_ip(water_surface.get_rect())

        # Step 3: Scale to viewport
        if source_rect.width > 0 and source_rect.height > 0:
            visible_water = water_surface.subsurface(source_rect)
            scaled_water = pygame.transform.scale(visible_water, surface.get_size())
            surface.blit(scaled_water, (0, 0))
    except (ValueError, pygame.error) as e:
        # Fallback to rect-based rendering if buffer creation fails
        print(f"Vectorized water rendering failed, using fallback: {e}", file=sys.stderr)
        water_overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        # Use same rounding as optimized path for consistency
        rounded_cam_x = round(camera.world_x)
        rounded_cam_y = round(camera.world_y)
        for sy in range(start_y, end_y):
            for sx in range(start_x, end_x):
                water = state.water_grid[sx, sy]
                if water <= 2:
                    continue

                if water <= 20:
                    alpha = 40 + (water * 3)
                    color = (100, 180, 230)
                elif water <= 50:
                    alpha = 100 + ((water - 20) * 2)
                    color = (60, 140, 210)
                else:
                    alpha = min(200, 160 + (water - 50))
                    color = (40, 100, 180)

                world_x, world_y = camera.cell_to_world(sx, sy)
                vp_x = (world_x - rounded_cam_x) * camera.zoom
                vp_y = (world_y - rounded_cam_y) * camera.zoom
                cell_size = max(1, scaled_cell_size)
                rect = pygame.Rect(int(vp_x), int(vp_y), cell_size, cell_size)
                pygame.draw.rect(water_overlay, (*color, alpha), rect)
        surface.blit(water_overlay, (0, 0))


def render_static_background(state: "GameState", font) -> pygame.Surface:
    """
    Render the entire static world (terrain) to a single surface.
    This is a one-time operation, and the surface is cached for performance.

    Renders all 180×135 grid cells with their biome colors and trench borders.
    """
    world_pixel_width = GRID_WIDTH * CELL_SIZE
    world_pixel_height = GRID_HEIGHT * CELL_SIZE
    background_surface = pygame.Surface((world_pixel_width, world_pixel_height))
    background_surface.fill(COLOR_BG_DARK)

    # Get cached elevation range for brightness scaling
    elevation_range = state.get_elevation_range()

    # Render all grid cells
    for sy in range(GRID_HEIGHT):
        for sx in range(GRID_WIDTH):
            # Get color from grids (no water on static background)
            color = get_grid_cell_color(state, sx, sy, elevation_range)

            # Position on the large background surface
            px = sx * CELL_SIZE
            py = sy * CELL_SIZE
            rect = pygame.Rect(px, py, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(background_surface, color, rect)

            # Draw trench border from the global grid
            if state.trench_grid is not None and state.trench_grid[sx, sy]:
                pygame.draw.rect(background_surface, COLOR_TRENCH, rect, 2)

    return background_surface


def redraw_background_rect(background_surface: pygame.Surface, state: "GameState", font, rect: pygame.Rect) -> None:
    """Redraw a single grid cell onto the cached background surface."""
    sx = rect.x // CELL_SIZE
    sy = rect.y // CELL_SIZE

    # Bounds check
    if not (0 <= sx < GRID_WIDTH and 0 <= sy < GRID_HEIGHT):
        return

    # Get cached elevation range and calculate color from grids
    elevation_range = state.get_elevation_range()
    color = get_grid_cell_color(state, sx, sy, elevation_range)

    # Draw the updated grid cell directly onto the background surface
    pygame.draw.rect(background_surface, color, rect)

    # Draw trench indicator from the global grid
    if state.trench_grid is not None and state.trench_grid[sx, sy]:
        pygame.draw.rect(background_surface, COLOR_TRENCH, rect, 2)


def get_tool_highlight_color(
    tool: Optional["Tool"],
    is_valid: bool,
) -> Tuple[int, int, int]:
    """Get the highlight color for a tool, using the pre-calculated validity."""
    if tool is None:
        return HIGHLIGHT_COLORS["default"]

    tool_id = tool.id.lower()

    if tool_id == "build":
        return HIGHLIGHT_COLORS["build"] if is_valid else HIGHLIGHT_COLORS["build_invalid"]
    elif tool_id in HIGHLIGHT_COLORS:
        return HIGHLIGHT_COLORS[tool_id]

    return HIGHLIGHT_COLORS["default"]


def _get_trench_affected_squares(
    player_pos: Tuple[int, int],
    target_pos: Tuple[int, int],
) -> dict[str, Tuple[int, int] | None]:
    """Calculate squares affected by trenching operation.

    Returns dict with keys: 'origin', 'exit', 'left', 'right'
    """
    px, py = player_pos
    tx, ty = target_pos

    # Direction vector
    dx = tx - px
    dy = ty - py
    length = math.sqrt(dx**2 + dy**2)

    if length == 0:
        return {'origin': None, 'exit': None, 'left': None, 'right': None}

    # Normalized direction
    dx_norm = round(dx / length)
    dy_norm = round(dy / length)

    # Perpendicular vectors
    left_dx, left_dy = -dy, dx
    right_dx, right_dy = dy, -dx

    # Normalize perpendicular
    left_len = math.sqrt(left_dx**2 + left_dy**2)
    right_len = math.sqrt(right_dx**2 + right_dy**2)

    if left_len > 0:
        left_dx = round(left_dx / left_len)
        left_dy = round(left_dy / left_len)
    if right_len > 0:
        right_dx = round(right_dx / right_len)
        right_dy = round(right_dy / right_len)

    # Calculate positions
    origin = (tx - dx_norm, ty - dy_norm)
    exit_sq = (tx + dx_norm, ty + dy_norm)
    left = (tx + left_dx, ty + left_dy)
    right = (tx + right_dx, ty + right_dy)

    # Validate bounds
    def in_bounds(pos):
        return 0 <= pos[0] < GRID_WIDTH and 0 <= pos[1] < GRID_HEIGHT

    return {
        'origin': origin if in_bounds(origin) else None,
        'exit': exit_sq if in_bounds(exit_sq) else None,
        'left': left if in_bounds(left) else None,
        'right': right if in_bounds(right) else None,
    }


def render_interaction_highlights(
    surface: pygame.Surface,
    camera: "Camera",
    player_pos: Tuple[int, int],
    ui_state: "UIState",
    tool: Optional["Tool"],
    scaled_cell_size: int,
) -> None:
    """Render interaction range indicator and target highlight."""
    target_cell = ui_state.target_cell
    if target_cell is None:
        return

    sub_size = scaled_cell_size

    # Check if this is a trench tool
    is_trench = tool and tool.get_current_option() and tool.get_current_option().id in ["trench_flat", "slope_down", "slope_up"]

    if is_trench:
        # Render trench-affected squares with color coding
        affected = _get_trench_affected_squares(player_pos, target_cell)

        # Color scheme: origin=red, exit=green, sides=blue, target=yellow
        highlights = [
            (affected['origin'], (200, 60, 60), 40),    # Red - origin
            (affected['exit'], (60, 200, 60), 40),      # Green - exit
            (affected['left'], (60, 60, 200), 40),      # Blue - left side
            (affected['right'], (60, 60, 200), 40),     # Blue - right side
            (target_cell, (200, 200, 60), 60),     # Yellow - target
        ]

        for pos, color, alpha in highlights:
            if pos is None:
                continue
            world_x, world_y = camera.cell_to_world(pos[0], pos[1])
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            if sub_size > 0:
                # Light shading
                highlight_surface = _get_cached_highlight_surface(sub_size, color, alpha)
                surface.blit(highlight_surface, (int(vp_x), int(vp_y)))

            # Border
            rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)
            pygame.draw.rect(surface, color, rect, 2)
    else:
        # Standard single-square highlight for non-trench tools
        color = get_tool_highlight_color(tool, ui_state.is_valid_target)
        world_x, world_y = camera.cell_to_world(target_cell[0], target_cell[1])
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)

        # Use cached highlight surface to avoid per-frame allocation
        if sub_size > 0:
            highlight_surface = _get_cached_highlight_surface(sub_size, color, 60)
            surface.blit(highlight_surface, (int(vp_x), int(vp_y)))
        pygame.draw.rect(surface, color, rect, 2)
