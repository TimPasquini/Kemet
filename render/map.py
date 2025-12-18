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

from mapgen import TILE_TYPES
from surface_state import compute_surface_appearance
from render.colors import color_for_tile, color_for_subsquare
from render.primitives import draw_text
from config import (
    STRUCTURE_INSET,
    TRENCH_INSET,
    WELLSPRING_RADIUS,
    PLAYER_RADIUS,
    SUBGRID_SIZE,
    INTERACTION_RANGE,
    SUB_TILE_SIZE,
    TILE_SIZE,
)
from subgrid import (
    subgrid_to_tile,
    get_subsquare_index,
    chebyshev_distance,
)

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


# =============================================================================
# Highlight Colors by Tool Type
# =============================================================================
HIGHLIGHT_COLORS = {
    "build": (80, 140, 200),      # Blue for building
    "build_invalid": (200, 80, 80),  # Red for invalid placement
    "shovel": (200, 180, 80),     # Yellow for terrain
    "bucket": (80, 180, 200),     # Cyan for water
    "survey": (80, 200, 120),     # Green for survey
    "default": (180, 180, 180),   # White/gray for no tool
}


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
    surface.fill((20, 20, 25))

    if background_surface is not None:
        # --- 1. Blit the pre-rendered static background ---
        # Get the portion of the background surface that is visible to the camera
        cam_x = -camera.world_to_viewport(0, 0)[0]
        cam_y = -camera.world_to_viewport(0, 0)[1]
        visible_world_rect = pygame.Rect(cam_x, cam_y, camera.viewport_width, camera.viewport_height)
        surface.blit(background_surface, (0, 0), visible_world_rect)
    else:
        # Fallback: render terrain per-frame (slower but works without background cache)
        _render_terrain_per_frame(surface, state, camera, tile_size, elevation_range)

    # --- 2. Draw dynamic elements on top of the background ---
    # Get visible tile range for structures and special features
    start_tx, start_ty, end_tx, end_ty = camera.get_visible_tile_range()

    # Draw structures (keyed by sub-square coords, rendered at sub-square position)
    sub_size = tile_size // SUBGRID_SIZE
    for (sub_x, sub_y), structure in state.structures.items():
        # Convert sub-square to tile for visibility check
        tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
        if not camera.is_tile_visible(tile_x, tile_y):
            continue
        # Get world position for sub-square (using sub-square coords directly)
        world_x = sub_x * sub_size
        world_y = sub_y * sub_size
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), sub_size - 1, sub_size - 1)
        pygame.draw.rect(surface, (30, 30, 30), rect.inflate(-2, -2))
        # Draw structure initial centered in sub-square
        draw_text(surface, font, structure.kind[0].upper(), (rect.x + sub_size // 3, rect.y + sub_size // 4))

    # Draw special features (wellsprings, depots) - only visible tiles
    for ty in range(start_ty, end_ty):
        for tx in range(start_tx, end_tx):
            tile = state.tiles[tx][ty]
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)

            if tile.wellspring_output > 0:
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(surface, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(surface, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(surface, font, "D", (rect.x + 18, rect.y + 12), color=(40, 40, 20))

    # Render sub-grid water overlay (dynamic, so drawn on top of static background)
    render_subgrid_water(surface, state, camera, tile_size)


def _render_terrain_per_frame(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    tile_size: int,
    elevation_range: Tuple[float, float],
) -> None:
    """Fallback terrain rendering - renders each visible sub-square per frame."""
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()

    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            tile_x = sub_x // SUBGRID_SIZE
            tile_y = sub_y // SUBGRID_SIZE
            local_x = sub_x % SUBGRID_SIZE
            local_y = sub_y % SUBGRID_SIZE

            tile = state.tiles[tile_x][tile_y]
            subsquare = tile.subgrid[local_x][local_y]

            sub_elevation = tile.get_subsquare_elevation(local_x, local_y)
            color = color_for_subsquare(subsquare, sub_elevation, tile, elevation_range)

            world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), SUB_TILE_SIZE, SUB_TILE_SIZE)
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
    sub_size = tile_size // SUBGRID_SIZE
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()

    # Create a single overlay surface for the entire viewport.
    water_overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
            local_x, local_y = get_subsquare_index(sub_x, sub_y)

            tile = state.tiles[tile_x][tile_y]
            water = tile.subgrid[local_x][local_y].surface_water

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
    Render the entire static world (terrain) to a single surface.
    This is a one-time operation, and the surface is cached for performance.
    """
    world_pixel_width = state.width * TILE_SIZE
    world_pixel_height = state.height * TILE_SIZE
    background_surface = pygame.Surface((world_pixel_width, world_pixel_height))
    background_surface.fill((20, 20, 25))

    # Get cached elevation range for brightness scaling
    elevation_range = state.get_elevation_range()

    world_sub_width = state.width * SUBGRID_SIZE
    world_sub_height = state.height * SUBGRID_SIZE

    for sub_y in range(world_sub_height):
        for sub_x in range(world_sub_width):
            tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
            local_x, local_y = get_subsquare_index(sub_x, sub_y)

            tile = state.tiles[tile_x][tile_y]
            subsquare = tile.subgrid[local_x][local_y]

            # Get elevation for this sub-square
            sub_elevation = tile.get_subsquare_elevation(local_x, local_y)

            # Use same color logic as per-frame rendering (includes elevation brightness)
            color = color_for_subsquare(subsquare, sub_elevation, tile, elevation_range)

            # Position on the large background surface
            px = sub_x * SUB_TILE_SIZE
            py = sub_y * SUB_TILE_SIZE
            rect = pygame.Rect(px, py, SUB_TILE_SIZE, SUB_TILE_SIZE)
            pygame.draw.rect(background_surface, color, rect)

            # Draw static features directly onto the background
            appearance = subsquare.get_appearance(tile)
            if "trench" in appearance.features:
                # Draw a visible border around trenched subsquares
                pygame.draw.rect(background_surface, (60, 100, 120), rect, 2)

    return background_surface


def redraw_background_rect(background_surface: pygame.Surface, state: "GameState", font, rect: pygame.Rect) -> None:
    """Redraw a single sub-square onto the cached background surface."""
    sub_x = rect.x // SUB_TILE_SIZE
    sub_y = rect.y // SUB_TILE_SIZE

    # Bounds check
    world_sub_width = state.width * SUBGRID_SIZE
    world_sub_height = state.height * SUBGRID_SIZE
    if not (0 <= sub_x < world_sub_width and 0 <= sub_y < world_sub_height):
        return

    tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
    local_x, local_y = get_subsquare_index(sub_x, sub_y)
    tile = state.tiles[tile_x][tile_y]
    subsquare = tile.subgrid[local_x][local_y]

    # Get cached elevation range and calculate color with brightness
    elevation_range = state.get_elevation_range()
    sub_elevation = tile.get_subsquare_elevation(local_x, local_y)
    color = color_for_subsquare(subsquare, sub_elevation, tile, elevation_range)

    # Draw the updated sub-square directly onto the background surface
    pygame.draw.rect(background_surface, color, rect)

    # Draw trench indicator if present
    appearance = subsquare.get_appearance(tile)
    if "trench" in appearance.features:
        pygame.draw.rect(background_surface, (60, 100, 120), rect, 2)


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


def render_interaction_highlights(
    surface: pygame.Surface,
    camera: "Camera",
    player_pos: Tuple[int, int],
    ui_state: "UIState",
    tool: Optional["Tool"],
) -> None:
    """Render interaction range indicator and target highlight."""
    target_subsquare = ui_state.target_subsquare
    if target_subsquare is None:
        return

    sub_size = int(camera.sub_tile_size)
    # Use the validity flag from ui_state to determine the color
    color = get_tool_highlight_color(tool, ui_state.is_valid_target)
    world_x, world_y = camera.subsquare_to_world(target_subsquare[0], target_subsquare[1])
    vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
    rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)

    # Use cached highlight surface to avoid per-frame allocation
    highlight_surface = _get_cached_highlight_surface(sub_size, color, 60)
    surface.blit(highlight_surface, (int(vp_x), int(vp_y)))
    pygame.draw.rect(surface, color, rect, 2)
