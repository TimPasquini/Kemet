# render/player_renderer.py
"""Player rendering module."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
import pygame

from render.config import COLOR_PLAYER, COLOR_PLAYER_ACTION_BG, COLOR_PLAYER_ACTION_BAR

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera

def render_player(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    player_world_pos: Tuple[float, float],
    scaled_cell_size: int
) -> None:
    """Render the player character."""
    px, py = player_world_pos
    vx, vy = camera.world_to_viewport(px, py)

    # Player radius is roughly half a grid cell (diameter = cell size)
    # We clamp it to a minimum of 2 pixels so it doesn't disappear at high zoom out
    radius = max(2, int(scaled_cell_size / 2))
    
    pygame.draw.circle(surface, COLOR_PLAYER, (int(vx), int(vy)), radius)
    pygame.draw.circle(surface, (0, 0, 0), (int(vx), int(vy)), radius, 1)

    # Draw action timer bar if busy
    if state.is_busy():
        bar_width = max(10, int(scaled_cell_size))
        bar_height = max(2, int(scaled_cell_size / 6))
        
        bar_x = int(vx - bar_width / 2)
        bar_y = int(vy - radius - bar_height - 4)
        
        progress = state.get_action_progress()
        
        pygame.draw.rect(surface, COLOR_PLAYER_ACTION_BG, (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(surface, COLOR_PLAYER_ACTION_BAR, (bar_x, bar_y, int(bar_width * progress), bar_height))
