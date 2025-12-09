# render/map.py
"""Map, tile, structure, and player rendering."""
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


def render_map(
    screen,
    font,
    state: "GameState",
    tile_size: int,
    elevation_range: Tuple[float, float],
) -> None:
    """Render the tile map, structures, and special features."""
    # Draw base tiles
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            color = color_for_tile(tile, TILE_TYPES[tile.kind], elevation_range)
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            pygame.draw.rect(screen, color, rect)
            if tile.trench:
                pygame.draw.rect(screen, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))

    # Draw structures
    for (x, y), structure in state.structures.items():
        rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
        pygame.draw.rect(screen, (30, 30, 30), rect.inflate(-STRUCTURE_INSET, -STRUCTURE_INSET))
        draw_text(screen, font, structure.kind[0].upper(), (rect.x + 6, rect.y + 4))

    # Draw special tile features (wellsprings, depots)
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            if tile.wellspring_output > 0:
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(screen, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))


def render_player(
    screen,
    state: "GameState",
    player_px: Tuple[float, float],
    tile_size: int,
) -> None:
    """Render the player circle and action progress bar."""
    player_center_x, player_center_y = int(player_px[0]), int(player_px[1])

    # Draw player circle
    pygame.draw.circle(
        screen,
        (240, 240, 90),
        (player_center_x, player_center_y),
        tile_size // PLAYER_RADIUS_DIVISOR,
    )

    # Draw action timer bar if busy
    if state.is_busy():
        bar_width = tile_size
        bar_height = 4
        bar_x = player_center_x - bar_width // 2
        bar_y = player_center_y - tile_size // 2 - bar_height - 2

        progress = state.get_action_progress()

        pygame.draw.rect(screen, (50, 50, 50), (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(screen, (200, 200, 80), (bar_x, bar_y, int(bar_width * progress), bar_height))
