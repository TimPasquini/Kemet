# render/minimap.py
"""Minimap rendering system."""
from __future__ import annotations

import pygame
import numpy as np
from typing import TYPE_CHECKING

from config import GRID_WIDTH, GRID_HEIGHT

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera


def render_minimap(
    surface: pygame.Surface,
    state: "GameState",
    camera: "Camera",
    rect: pygame.Rect
) -> None:
    """Render the minimap to the given surface within the specified rect."""
    
    # Draw background/border
    pygame.draw.rect(surface, (20, 20, 25), rect)
    pygame.draw.rect(surface, (60, 60, 70), rect, 1)
    
    # Calculate scale - sample every 3rd grid cell for minimap display
    # This gives us a 60×45 minimap from the 180×135 grid
    sample_step = 3
    minimap_w = GRID_WIDTH // sample_step
    minimap_h = GRID_HEIGHT // sample_step

    # Size of each minimap pixel
    scale_x = rect.width / minimap_w
    scale_y = rect.height / minimap_h

    # Draw minimap by sampling every 3rd grid cell
    from render.grid_helpers import get_exposed_material, APPEARANCE_TYPES, DEFAULT_COLOR

    for mx in range(minimap_w):
        for my in range(minimap_h):
            # Sample grid cell (every 3rd cell)
            sx = mx * sample_step
            sy = my * sample_step

            # Get material-based color from this grid cell
            material = get_exposed_material(state, sx, sy)
            color = APPEARANCE_TYPES.get(material, DEFAULT_COLOR)

            # Darken for minimap display
            color = tuple(int(c * 0.7) for c in color)

            # Show water - check this cell's water
            surface_water = state.water_grid[sx, sy]
            subsurface_water = np.sum(state.subsurface_water_grid[:, sx, sy])
            total_water = surface_water + subsurface_water

            if total_water > 15:  # Threshold for showing water on minimap
                color = (60, 100, 180)

            # Show depot - check if this cell has a depot structure
            if (sx, sy) in state.structures and state.structures[(sx, sy)].kind == "depot":
                color = (200, 50, 50)

            # Draw minimap pixel
            px = rect.x + int(mx * scale_x)
            py = rect.y + int(my * scale_y)
            w = max(1, int(scale_x) + 1)
            h = max(1, int(scale_y) + 1)
            surface.fill(color, (px, py, w, h))

    # Draw Player (map grid position to minimap coordinates)
    player_sx, player_sy = state.player_state.position
    player_mx = player_sx // sample_step
    player_my = player_sy // sample_step
    px = rect.x + int(player_mx * scale_x)
    py = rect.y + int(player_my * scale_y)
    pygame.draw.circle(surface, (255, 255, 0), (px, py), 2)

    # Draw Camera Viewport Frame
    start_sx, start_sy, end_sx, end_sy = camera.get_visible_subsquare_range()

    view_rect = pygame.Rect(
        rect.x + (start_sx // sample_step) * scale_x,
        rect.y + (start_sy // sample_step) * scale_y,
        ((end_sx - start_sx) // sample_step) * scale_x,
        ((end_sy - start_sy) // sample_step) * scale_y
    )
    pygame.draw.rect(surface, (255, 255, 255), view_rect, 1)