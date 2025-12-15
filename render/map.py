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
    """
    surface.fill((20, 20, 25))

    # Get visible sub-square range from camera
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()

    # Draw visible sub-squares (each with its own biome)
    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            # Get tile and local coords
            tile_x = sub_x // SUBGRID_SIZE
            tile_y = sub_y // SUBGRID_SIZE
            local_x = sub_x % SUBGRID_SIZE
            local_y = sub_y % SUBGRID_SIZE

            tile = state.tiles[tile_x][tile_y]
            subsquare = tile.subgrid[local_x][local_y]

            # Get color based on sub-square's biome
            sub_elevation = tile.get_subsquare_elevation(local_x, local_y)
            color = color_for_subsquare(subsquare.biome, sub_elevation, tile, elevation_range)

            # Convert sub-square position to viewport position
            world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), SUB_TILE_SIZE, SUB_TILE_SIZE)
            pygame.draw.rect(surface, color, rect)

    # Draw tile-level features (trenches) - over sub-squares
    start_tx, start_ty, end_tx, end_ty = camera.get_visible_tile_range()
    for ty in range(start_ty, end_ty):
        for tx in range(start_tx, end_tx):
            tile = state.tiles[tx][ty]
            if tile.trench:
                world_x, world_y = camera.tile_to_world(tx, ty)
                vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
                rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)
                pygame.draw.rect(surface, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))

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

    # Render sub-grid water overlay
    render_subgrid_water(surface, state, camera, tile_size)


def render_subgrid_water(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    tile_size: int,
) -> None:
    """Render water levels at sub-grid resolution as semi-transparent overlay.

    Water is shown as blue tint, more opaque = more water.
    Only renders sub-squares with significant water (> 2 units).
    """
    sub_size = tile_size // SUBGRID_SIZE

    # Get visible sub-square range
    start_x, start_y, end_x, end_y = camera.get_visible_subsquare_range()

    for sub_y in range(start_y, end_y):
        for sub_x in range(start_x, end_x):
            # Get tile and local coords
            tile_x = sub_x // SUBGRID_SIZE
            tile_y = sub_y // SUBGRID_SIZE
            local_x = sub_x % SUBGRID_SIZE
            local_y = sub_y % SUBGRID_SIZE

            tile = state.tiles[tile_x][tile_y]
            water = tile.subgrid[local_x][local_y].surface_water

            # Skip if negligible water
            if water <= 2:
                continue

            # Calculate water color/opacity based on amount
            # Light water: 3-20 units, Medium: 21-50, Heavy: 51+
            if water <= 20:
                alpha = 40 + (water * 3)  # 40-100 alpha
                color = (100, 180, 230)   # Light blue
            elif water <= 50:
                alpha = 100 + ((water - 20) * 2)  # 100-160 alpha
                color = (60, 140, 210)    # Medium blue
            else:
                alpha = min(200, 160 + (water - 50))  # 160-200 alpha
                color = (40, 100, 180)    # Deep blue

            # Get sub-square screen position
            world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            # Draw semi-transparent water rectangle
            water_surface = pygame.Surface((sub_size, sub_size), pygame.SRCALPHA)
            water_surface.fill((*color, alpha))
            surface.blit(water_surface, (int(vp_x), int(vp_y)))


def render_player(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    player_world_pos: Tuple[float, float],
    tile_size: int,
) -> None:
    """Render the player circle and action progress bar.

    Args:
        surface: Surface to render to
        state: Game state (for action timer)
        camera: Camera for coordinate transform
        player_world_pos: Player position in world coordinates
        tile_size: Size of each tile in pixels
    """
    # Transform player world position to viewport position
    vp_x, vp_y = camera.world_to_viewport(player_world_pos[0], player_world_pos[1])
    player_x, player_y = int(vp_x), int(vp_y)

    # Draw player circle (sized relative to sub-tile, not simulation tile)
    pygame.draw.circle(
        surface,
        (240, 240, 90),
        (player_x, player_y),
        PLAYER_RADIUS,
    )

    # Draw action timer bar if busy
    if state.is_busy():
        bar_width = SUB_TILE_SIZE
        bar_height = 4
        bar_x = player_x - bar_width // 2
        bar_y = player_y - SUB_TILE_SIZE // 2 - bar_height - 2
        progress = state.get_action_progress()
        pygame.draw.rect(surface, (50, 50, 50), (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(surface, (200, 200, 80), (bar_x, bar_y, int(bar_width * progress), bar_height))


def render_night_overlay(
    surface: pygame.Surface,
    heat: int,
) -> None:
    """Render the night darkness overlay based on heat level.

    Args:
        surface: Surface to render overlay to
        heat: Current heat value (lower = darker night)
    """
    night_alpha = max(0, min(200, int((140 - heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        surface.blit(overlay, (0, 0))


# =============================================================================
# Interaction Highlighting
# =============================================================================

def get_tool_highlight_color(
    tool: Optional["Tool"],
    state: "GameState",
    target_subsquare: Tuple[int, int],
) -> Tuple[int, int, int]:
    """Get the highlight color for a tool at a given target position.

    Args:
        tool: Currently selected tool (or None)
        state: Game state for validation
        target_subsquare: Target position in sub-grid coords

    Returns:
        RGB color tuple for the highlight
    """
    if tool is None:
        return HIGHLIGHT_COLORS["default"]

    tool_id = tool.id.lower()

    if tool_id == "build":
        # Check if target sub-square is valid for building
        tile_x, tile_y = subgrid_to_tile(*target_subsquare)
        if 0 <= tile_x < state.width and 0 <= tile_y < state.height:
            tile = state.tiles[tile_x][tile_y]
            # Invalid if: sub-square has structure, tile is rock, or tile is depot
            if target_subsquare in state.structures or tile.kind == "rock" or tile.depot:
                return HIGHLIGHT_COLORS["build_invalid"]
        return HIGHLIGHT_COLORS["build"]

    elif tool_id == "shovel":
        return HIGHLIGHT_COLORS["shovel"]

    elif tool_id == "bucket":
        return HIGHLIGHT_COLORS["bucket"]

    elif tool_id == "survey":
        return HIGHLIGHT_COLORS["survey"]

    return HIGHLIGHT_COLORS["default"]


def render_interaction_highlights(
    surface: pygame.Surface,
    camera: "Camera",
    player_pos: Tuple[int, int],
    target_subsquare: Optional[Tuple[int, int]],
    tool: Optional["Tool"],
    state: "GameState",
) -> None:
    """Render interaction range indicator and target highlight.

    Args:
        surface: Surface to render to
        camera: Camera for coordinate transforms
        player_pos: Player position in sub-grid coordinates
        target_subsquare: Currently targeted sub-square (or None)
        tool: Currently selected tool
        state: Game state for validation
    """
    sub_size = int(camera.sub_tile_size)
    tile_size = camera.tile_size

    # Get visible range for culling
    vis_start_x, vis_start_y, vis_end_x, vis_end_y = camera.get_visible_subsquare_range()

    # Calculate world dimensions in sub-squares
    world_sub_width = state.width * SUBGRID_SIZE
    world_sub_height = state.height * SUBGRID_SIZE

    # Draw target highlight (cursor snaps to valid squares, no range outline needed)
    if target_subsquare is not None:
        sub_x, sub_y = target_subsquare

        # Bounds and visibility check
        if (0 <= sub_x < world_sub_width and 0 <= sub_y < world_sub_height and
            vis_start_x <= sub_x < vis_end_x and vis_start_y <= sub_y < vis_end_y):

            color = get_tool_highlight_color(tool, state, target_subsquare)
            tool_id = tool.id.lower() if tool else ""

            # For build tool, show tile-sized preview
            if tool_id == "build":
                tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
                tile_world_x, tile_world_y = camera.tile_to_world(tile_x, tile_y)
                tile_vp_x, tile_vp_y = camera.world_to_viewport(tile_world_x, tile_world_y)
                tile_rect = pygame.Rect(int(tile_vp_x), int(tile_vp_y), tile_size, tile_size)

                # Draw tile-sized semi-transparent preview
                preview_surface = pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)
                preview_surface.fill((*color, 40))  # More transparent for tile preview
                surface.blit(preview_surface, (int(tile_vp_x), int(tile_vp_y)))

                # Draw tile border
                pygame.draw.rect(surface, color, tile_rect, 2)
            else:
                # Standard sub-square highlight for other tools
                world_x, world_y = camera.subsquare_to_world(sub_x, sub_y)
                vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
                rect = pygame.Rect(int(vp_x), int(vp_y), sub_size, sub_size)

                # Draw filled semi-transparent highlight
                highlight_surface = pygame.Surface((sub_size, sub_size), pygame.SRCALPHA)
                highlight_surface.fill((*color, 60))  # Semi-transparent fill
                surface.blit(highlight_surface, (int(vp_x), int(vp_y)))

                # Draw solid border
                pygame.draw.rect(surface, color, rect, 2)
