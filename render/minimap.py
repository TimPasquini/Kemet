# render/minimap.py
"""Minimap rendering system."""
from __future__ import annotations

import pygame
import numpy as np
from typing import TYPE_CHECKING
from core.config import GRID_WIDTH, GRID_HEIGHT
from simulation.surface import compute_exposed_layer_grid
from world.terrain import SoilLayer
from .grid_helpers import APPEARANCE_TYPES, DEFAULT_COLOR

if TYPE_CHECKING:
    from game_state import GameState
    from core.camera import Camera


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

    # --- Vectorized Minimap Generation ---
    # This approach generates an RGB numpy array for the entire map and then
    # downsamples it, which is much faster than iterating through cells.

    # 1. Get exposed materials for the entire grid
    exposed_layer_indices = compute_exposed_layer_grid(state.terrain_layers)
    exposed_layer_indices[exposed_layer_indices == -1] = SoilLayer.BEDROCK

    # Use advanced indexing to get material names
    W, H = exposed_layer_indices.shape
    row_indices, col_indices = np.ogrid[:W, :H]
    exposed_materials = state.terrain_materials[exposed_layer_indices, row_indices, col_indices]

    # 2. Create an RGB image array from materials
    rgb_array = np.full((W, H, 3), DEFAULT_COLOR, dtype=np.uint8)
    for mat, color in APPEARANCE_TYPES.items():
        dark_color = tuple(int(c * 0.7) for c in color)
        rgb_array[exposed_materials == mat] = dark_color

    # 3. Overlay water
    total_water = state.water_grid + np.sum(state.subsurface_water_grid, axis=0)
    water_mask = total_water > 15
    rgb_array[water_mask] = (60, 100, 180)

    # 4. Downsample the final RGB array. This is the "sampling" step.
    sample_step = 1
    downsampled_rgb = rgb_array[::sample_step, ::sample_step, :]

    # 5. Create a small Pygame surface and scale it to the target rect.
    minimap_surface = pygame.surfarray.make_surface(downsampled_rgb)
    scaled_minimap = pygame.transform.scale(minimap_surface, rect.size)
    surface.blit(scaled_minimap, rect.topleft)

    # --- Draw Overlays (Player, Depot, Camera) ---
    # Calculate scale factors for overlay positions
    minimap_w = GRID_WIDTH // sample_step
    minimap_h = GRID_HEIGHT // sample_step
    scale_x = rect.width / minimap_w
    scale_y = rect.height / minimap_h
    for (sx, sy), structure in state.structures.items():
        if structure.kind == "depot":
            # Map grid position to minimap coordinates
            mx = sx // sample_step
            my = sy // sample_step
            
            px = rect.x + int(mx * scale_x)
            py = rect.y + int(my * scale_y)
            
            # Draw depot (Red)
            pygame.draw.rect(surface, (200, 50, 50), (px, py, max(3, int(scale_x)+1), max(3, int(scale_y)+1)))

    # Draw Player (map grid position to minimap coordinates)
    player_sx, player_sy = state.player_state.position
    player_mx = player_sx // sample_step
    player_my = player_sy // sample_step
    px = rect.x + int(player_mx * scale_x)
    py = rect.y + int(player_my * scale_y)
    pygame.draw.circle(surface, (255, 255, 0), (px, py), 2)

    # Draw Camera Viewport Frame
    start_sx, start_sy, end_sx, end_sy = camera.get_visible_cell_range()

    view_rect = pygame.Rect(
        rect.x + (start_sx // sample_step) * scale_x,
        rect.y + (start_sy // sample_step) * scale_y,
        ((end_sx - start_sx) // sample_step) * scale_x,
        ((end_sy - start_sy) // sample_step) * scale_y
    )
    pygame.draw.rect(surface, (255, 255, 255), view_rect, 1)