# render/minimap.py
"""Minimap rendering system."""
from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

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
    
    # Draw tiles (simplified)
    # For performance on large maps, we might want to cache this surface
    # and only update it when terrain changes. For now, direct draw is okay for 60x45.
    for x in range(map_w_tiles):
        for y in range(map_h_tiles):
            tile = state.tiles[x][y]
            
            # Simple color coding
            color = (100, 100, 80) # Default dirt
            
            if tile.kind == "rock":
                color = (80, 80, 80)
            elif tile.kind == "dune":
                color = (180, 160, 100)
            elif tile.kind == "wadi":
                color = (120, 100, 80)
            elif tile.kind == "salt":
                color = (200, 200, 200)
                
            # Show water
            if tile.hydration > 5:
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