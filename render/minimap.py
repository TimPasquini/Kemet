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
    
    # Calculate scale
    # We want to fit the whole map into the rect (aggregated in 3×3 regions for minimap)
    map_w_regions = GRID_WIDTH // 3
    map_h_regions = GRID_HEIGHT // 3

    # Size of a region on the minimap
    scale_x = rect.width / map_w_regions
    scale_y = rect.height / map_h_regions

    # Draw regions (aggregating 3×3 grid cells for minimap display)
    # Get material colors from the center cell of each 3×3 region
    from render.grid_helpers import get_exposed_material, APPEARANCE_TYPES, DEFAULT_COLOR

    for x in range(map_w_regions):
        for y in range(map_h_regions):
            # Get center cell of tile's 3x3 grid region
            center_sx = x * 3 + 1
            center_sy = y * 3 + 1

            # Get material-based color from grids
            material = get_exposed_material(state, center_sx, center_sy)
            color = APPEARANCE_TYPES.get(material, DEFAULT_COLOR)

            # Darken for minimap display (make it less bright)
            color = tuple(int(c * 0.7) for c in color)

            # Show water (check grids instead of tile.hydration)
            # Sum surface + subsurface water for this tile's 3x3 grid region
            sx_start, sy_start = x * 3, y * 3
            sx_end, sy_end = sx_start + 3, sy_start + 3

            surface_water = np.sum(state.water_grid[sx_start:sx_end, sy_start:sy_end])
            subsurface_water = np.sum(state.subsurface_water_grid[:, sx_start:sx_end, sy_start:sy_end])
            total_water = surface_water + subsurface_water

            if total_water > 50:  # Threshold for showing water on minimap
                color = (60, 100, 180)

            # Show depot - check if any subsquare on this tile has a depot structure
            has_depot = False
            sx_base, sy_base = (x * 3, y * 3)
            for dx in range(3):
                for dy in range(3):
                    sub_pos = (sx_base + dx, sy_base + dy)
                    if sub_pos in state.structures and state.structures[sub_pos].kind == "depot":
                        has_depot = True
                        break
                if has_depot:
                    break

            if has_depot:
                color = (200, 50, 50)

            # Draw pixel
            px = rect.x + int(x * scale_x)
            py = rect.y + int(y * scale_y)
            # Draw slightly larger than 1x1 to avoid gaps if scale is non-integer
            w = max(1, int(scale_x) + 1)
            h = max(1, int(scale_y) + 1)
            surface.fill(color, (px, py, w, h))

    # Draw Player (convert grid position to region position for minimap)
    player_sx, player_sy = state.player_state.position
    player_region_x, player_region_y = player_sx // 3, player_sy // 3
    px = rect.x + int(player_region_x * scale_x)
    py = rect.y + int(player_region_y * scale_y)
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