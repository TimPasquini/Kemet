# render/player_renderer.py
"""Player rendering module."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
import pygame

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
    
    # Scale player size with zoom
    # Base radius 5 (diameter 10) at zoom 1.0, which matches a sub-square size roughly
    radius = max(3, int(5 * camera.zoom))
    
    pygame.draw.circle(surface, (255, 255, 0), (int(vx), int(vy)), radius)
    pygame.draw.circle(surface, (0, 0, 0), (int(vx), int(vy)), radius, 1)