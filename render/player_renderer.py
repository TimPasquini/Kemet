# render/player_renderer.py
"""Player rendering module."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
import pygame

from config import SUBGRID_SIZE

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera

def render_player(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    player_world_pos: Tuple[float, float],
    scaled_tile_size: int
) -> None:
    """Render the player character."""
    px, py = player_world_pos
    vx, vy = camera.world_to_viewport(px, py)
    
    # Calculate sub-tile size in pixels at current zoom
    scaled_sub_tile_size = scaled_tile_size / SUBGRID_SIZE
    
    # Player radius is roughly half a sub-tile (diameter = sub-tile size)
    # We clamp it to a minimum of 2 pixels so it doesn't disappear at high zoom out
    radius = max(2, int(scaled_sub_tile_size / 2))
    
    pygame.draw.circle(surface, (255, 255, 0), (int(vx), int(vy)), radius)
    pygame.draw.circle(surface, (0, 0, 0), (int(vx), int(vy)), radius, 1)
