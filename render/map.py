# render/map.py
"""Map, tile, structure, and player rendering with camera support.

Rendering now supports:
- Tile-level features (biome colors, structures)
- Sub-grid water visualization
- Interaction range highlights
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, Optional, List

import pygame

from world.terrain import TILE_TYPES
from render.primitives import draw_text
from render.grid_helpers import get_grid_cell_color, get_grid_elevation
from config import (
        INTERACTION_RANGE,
    GRID_WIDTH,
    GRID_HEIGHT,
)
from render.config import (
    STRUCTURE_INSET,
    TRENCH_INSET,
    WELLSPRING_RADIUS,
    PLAYER_RADIUS,
    SUB_TILE_SIZE,
    TILE_SIZE,
    COLOR_BG_DARK,
    COLOR_STRUCTURE,
    COLOR_WELLSPRING_STRONG,
    COLOR_WELLSPRING_WEAK,
    COLOR_DEPOT,
    COLOR_TRENCH,
    HIGHLIGHT_COLORS,
)
from utils import chebyshev_distance

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera
    from tools import Tool
    from ui_state import UIState

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
    tile_size: int,
    elevation_range: Tuple[float, float],
    background_surface: pygame.Surface = None,
) -> None:
    """Render the visible portion of the world to the map viewport surface.

    Renders at sub-square resolution - each sub-square has its own biome color.

    Args:
        surface: Surface to render to (sized to camera viewport)
        font: Font for text rendering
        state: Game state with tiles and structures
        camera: Camera defining visible region
        tile_size: Size of each simulation tile in pixels
        elevation_range: (min, max) elevation for color scaling
        background_surface: Pre-rendered static terrain (optional, falls back to per-frame render)
    """
    surface.fill(COLOR_BG_DARK)

    if background_surface is not None:
        # --- 1. Blit the pre-rendered static background ---
        # Determine the source rectangle from the full-world background surface
        # that corresponds to the camera's current view.
        src_w = camera.viewport_width / camera.zoom
        src_h = camera.viewport_height / camera.zoom
        source_rect = pygame.Rect(camera.world_x, camera.world_y, src_w, src_h)

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
        _render_terrain_per_frame(surface, state, camera, tile_size, elevation_range)

    # --- 2. Draw dynamic elements on top of the background ---
    # Get visible tile range for structures and special features
    start_tx, start_ty, end_tx, end_ty = camera.get_visible_tile_range()

    # Draw structures (keyed by sub-square coords, rendered at sub-square position)
    # Use SUB_TILE_SIZE directly to match background scaling
    scaled_sub_size = max(1, int(SUB_TILE_SIZE * camera.zoom))
    for (sub_x, sub_y), structure in state.structures.items():
        # Convert sub-square to tile for visibility check
        tile_x, tile_y = (sub_x // 3, sub_y // 3)
        if not camera.is_tile_visible(tile_x, tile_y):
            continue
        # Get world position for sub-square using camera method
        world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), scaled_sub_size, scaled_sub_size)
        pygame.draw.rect(surface, COLOR_STRUCTURE, rect.inflate(-2, -2))
        # Draw structure initial centered in sub-square
        if scaled_sub_size >= 8:  # Only draw letter if big enough
            draw_text(surface, font, structure.kind[0].upper(), (rect.x + scaled_sub_size // 3, rect.y + scaled_sub_size // 4))

    # Draw special features (wellsprings, depots) - only visible tiles
    for ty in range(start_ty, end_ty):
        for tx in range(start_tx, end_tx):
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)

            # Check wellspring from wellspring_grid (center cell of tile's 3x3 region)
            center_sx, center_sy = tx * 3 + 1, ty * 3 + 1
            wellspring_output = state.wellspring_grid[center_sx, center_sy] if state.wellspring_grid is not None else 0
            if wellspring_output > 0:
                spring_color = COLOR_WELLSPRING_STRONG if wellspring_output / 10 > 0.5 else COLOR_WELLSPRING_WEAK
                pygame.draw.circle(surface, spring_color, rect.center, WELLSPRING_RADIUS * camera.zoom)

            # NOTE: Depot rendering removed - depots are now rendered as single-cell structures
            # like all other buildings in the structure rendering loop above (lines 118-133)
            # Multi-cell structure layouts will be implemented properly in the future

    # Render sub-grid water overlay (dynamic, so drawn on top of static background)
    render_subgrid_water(surface, state, camera, tile_size)


def _render_terrain_per_frame(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    tile_size: int,
    elevation_range: Tuple[float, float],
) -> None:
    """Fallback terrain rendering - renders each visible sub-square per frame (grid-aware)."""
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()
    scaled_sub_tile_size = max(1, int((TILE_SIZE / 3) * camera.zoom))

    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            # Grid-aware color computation (no SubSquare access needed)
            color = get_grid_cell_color(state, sub_x, sub_y, elevation_range)

            world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), scaled_sub_tile_size, scaled_sub_tile_size)
            pygame.draw.rect(surface, color, rect)


def render_subgrid_water(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    tile_size: int,
) -> None:
    """
    Render water as a single semi-transparent overlay for performance.
    This avoids thousands of small blit calls per frame.
    """
    sub_size = max(1, tile_size // 3)
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()

    # Create a single overlay surface for the entire viewport.
    water_overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            # Grid-aware water rendering (no tile access needed)
            water = state.water_grid[sub_x, sub_y]

            if water <= 2:
                continue

            # Determine color and alpha based on water depth
            if water <= 20:
                alpha = 40 + (water * 3)
                color = (100, 180, 230)
            elif water <= 50:
                alpha = 100 + ((water - 20) * 2)
                color = (60, 140, 210)
            else:
                alpha = min(200, 160 + (water - 50))
                color = (40, 100, 180)

            # Get sub-square screen position
            world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
            rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)

            # Draw the water rectangle directly onto the single overlay surface
            pygame.draw.rect(water_overlay, (*color, alpha), rect)

    # Blit the entire water overlay onto the main surface once.
    surface.blit(water_overlay, (0, 0))


def render_static_background(state: "GameState", font) -> pygame.Surface:
    """
    Render the entire static world (terrain) to a single surface (grid-based).
    This is a one-time operation, and the surface is cached for performance.
    """
    world_pixel_width = GRID_WIDTH * SUB_TILE_SIZE
    world_pixel_height = GRID_HEIGHT * SUB_TILE_SIZE
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
            px = sx * SUB_TILE_SIZE
            py = sy * SUB_TILE_SIZE
            rect = pygame.Rect(px, py, SUB_TILE_SIZE, SUB_TILE_SIZE)
            pygame.draw.rect(background_surface, color, rect)

            # Draw trench border from the global grid
            if state.trench_grid is not None and state.trench_grid[sx, sy]:
                pygame.draw.rect(background_surface, COLOR_TRENCH, rect, 2)

    return background_surface


def redraw_background_rect(background_surface: pygame.Surface, state: "GameState", font, rect: pygame.Rect) -> None:
    """Redraw a single grid cell onto the cached background surface (grid-based)."""
    sx = rect.x // SUB_TILE_SIZE
    sy = rect.y // SUB_TILE_SIZE

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
    import math
    from config import GRID_WIDTH, GRID_HEIGHT

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
    scaled_sub_tile_size: int,
) -> None:
    """Render interaction range indicator and target highlight."""
    target_cell = ui_state.target_cell
    if target_cell is None:
        return

    sub_size = scaled_sub_tile_size

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
            world_x, world_y = camera.subsquare_to_world(pos[0], pos[1])
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
        world_x, world_y = camera.subsquare_to_world(target_cell[0], target_cell[1])
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)

        # Use cached highlight surface to avoid per-frame allocation
        if sub_size > 0:
            highlight_surface = _get_cached_highlight_surface(sub_size, color, 60)
            surface.blit(highlight_surface, (int(vp_x), int(vp_y)))
        pygame.draw.rect(surface, color, rect, 2)
