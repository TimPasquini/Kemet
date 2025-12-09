# render/map.py
"""Map, tile, structure, and player rendering with camera support."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

import pygame

from mapgen import TILE_TYPES
from render.colors import color_for_tile
from render.primitives import draw_text
from config import (
    STRUCTURE_INSET,
    TRENCH_INSET,
    WELLSPRING_RADIUS,
    PLAYER_RADIUS_DIVISOR,
)

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera


def render_map_viewport(
    surface: pygame.Surface,
    font,
    state: "GameState",
    camera: "Camera",
    tile_size: int,
    elevation_range: Tuple[float, float],
) -> None:
    """Render the visible portion of the world to the map viewport surface.

    Args:
        surface: Surface to render to (sized to camera viewport)
        font: Font for text rendering
        state: Game state with tiles and structures
        camera: Camera defining visible region
        tile_size: Size of each tile in pixels
        elevation_range: (min, max) elevation for color scaling
    """
    surface.fill((20, 20, 25))

    # Get visible tile range from camera
    start_x, start_y, end_x, end_y = camera.get_visible_tile_range()

    # Draw visible tiles
    for ty in range(start_y, end_y):
        for tx in range(start_x, end_x):
            tile = state.tiles[tx][ty]
            color = color_for_tile(tile, TILE_TYPES[tile.kind], elevation_range)

            # Convert tile position to viewport position
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)
            pygame.draw.rect(surface, color, rect)

            if tile.trench:
                pygame.draw.rect(surface, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))

    # Draw structures (only visible ones)
    for (sx, sy), structure in state.structures.items():
        if not camera.is_tile_visible(sx, sy):
            continue
        world_x, world_y = camera.tile_to_world(sx, sy)
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)
        pygame.draw.rect(surface, (30, 30, 30), rect.inflate(-STRUCTURE_INSET, -STRUCTURE_INSET))
        draw_text(surface, font, structure.kind[0].upper(), (rect.x + 6, rect.y + 4))

    # Draw special features (wellsprings, depots) - only visible tiles
    for ty in range(start_y, end_y):
        for tx in range(start_x, end_x):
            tile = state.tiles[tx][ty]
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)

            if tile.wellspring_output > 0:
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(surface, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(surface, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(surface, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))


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

    # Draw player circle
    pygame.draw.circle(
        surface,
        (240, 240, 90),
        (player_x, player_y),
        tile_size // PLAYER_RADIUS_DIVISOR,
    )

    # Draw action timer bar if busy
    if state.is_busy():
        bar_width = tile_size
        bar_height = 4
        bar_x = player_x - bar_width // 2
        bar_y = player_y - tile_size // 2 - bar_height - 2
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
