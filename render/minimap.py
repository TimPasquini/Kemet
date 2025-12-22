# render/minimap.py
"""Minimap rendering system."""
from __future__ import annotations

import pygame
import numpy as np
from typing import TYPE_CHECKING

from config import SUBGRID_SIZE

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
    
    # Calculate scale
    # We want to fit the whole map into the rect
    map_w_tiles = state.width
    map_h_tiles = state.height
    
    # Size of a tile on the minimap
    scale_x = rect.width / map_w_tiles
    scale_y = rect.height / map_h_tiles
    
    # Draw tiles (grid-based material colors)
    # Get material colors from the center cell of each tile's 3x3 region
    from render.grid_helpers import get_exposed_material, APPEARANCE_TYPES, DEFAULT_COLOR

    for x in range(map_w_tiles):
        for y in range(map_h_tiles):
            tile = state.tiles[x][y]

            # Get center cell of tile's 3x3 grid region
            center_sx = x * SUBGRID_SIZE + 1
            center_sy = y * SUBGRID_SIZE + 1

            # Get material-based color from grids
            material = get_exposed_material(state, center_sx, center_sy)
            color = APPEARANCE_TYPES.get(material, DEFAULT_COLOR)

            # Darken for minimap display (make it less bright)
            color = tuple(int(c * 0.7) for c in color)

            # Show water (check grids instead of tile.hydration)
            # Sum surface + subsurface water for this tile's 3x3 grid region
            sx_start, sy_start = x * SUBGRID_SIZE, y * SUBGRID_SIZE
            sx_end, sy_end = sx_start + SUBGRID_SIZE, sy_start + SUBGRID_SIZE

            surface_water = np.sum(state.water_grid[sx_start:sx_end, sy_start:sy_end])
            subsurface_water = np.sum(state.subsurface_water_grid[:, sx_start:sx_end, sy_start:sy_end])
            total_water = surface_water + subsurface_water

            if total_water > 50:  # Threshold for showing water on minimap
                color = (60, 100, 180)

            # Show depot
            if tile.depot:
                color = (200, 50, 50)
                
            # Draw pixel
            px = rect.x + int(x * scale_x)
            py = rect.y + int(y * scale_y)
            # Draw slightly larger than 1x1 to avoid gaps if scale is non-integer
            w = max(1, int(scale_x) + 1)
            h = max(1, int(scale_y) + 1)
            surface.fill(color, (px, py, w, h))

    # Draw Player
    player_tile = state.player
    px = rect.x + int(player_tile[0] * scale_x)
    py = rect.y + int(player_tile[1] * scale_y)
    pygame.draw.circle(surface, (255, 255, 0), (px, py), 2)
    
    # Draw Camera Viewport Frame
    # Calculate visible range in tiles
    start_x, start_y, end_x, end_y = camera.get_visible_tile_range()
    
    view_rect = pygame.Rect(
        rect.x + start_x * scale_x,
        rect.y + start_y * scale_y,
        (end_x - start_x) * scale_x,
        (end_y - start_y) * scale_y
    )
    pygame.draw.rect(surface, (255, 255, 255), view_rect, 1)