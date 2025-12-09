# render/hud.py
"""HUD panels: environment info, tile info, inventory, soil profile."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

import pygame

from ground import SoilLayer, MATERIAL_LIBRARY, units_to_meters
from render.primitives import draw_text, draw_section_header
from config import LINE_HEIGHT, SECTION_SPACING

if TYPE_CHECKING:
    from main import GameState


def render_hud(
    screen,
    font,
    state: "GameState",
    hud_x: int,
    start_y: int,
) -> int:
    """Render the main HUD panels (environment + current tile). Returns final y position."""
    y_offset = start_y

    # Environment section
    y_offset = draw_section_header(screen, font, "ENVIRONMENT", (hud_x, y_offset)) + 4
    draw_text(screen, font, f"Day: {state.day}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Time: {'Night' if state.is_night else 'Day'}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Heat: {state.heat}%", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Rain: {'Active' if state.raining else f'in {state.rain_timer}t'}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT + SECTION_SPACING

    # Current tile section
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))

    y_offset = draw_section_header(screen, font, "CURRENT TILE", (hud_x, y_offset)) + 4
    draw_text(screen, font, f"Position: ({x}, {y})", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Type: {tile.kind.capitalize()}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Elevation: {tile.elevation:.2f}m", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Water: {tile.water.total_water() / 10:.1f}L total", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"  Surface: {tile.water.surface_water / 10:.1f}L", (hud_x + 10, y_offset), (180, 180, 180))
    y_offset += LINE_HEIGHT

    if tile.water.total_subsurface_water() > 0:
        draw_text(screen, font, f"  Ground: {tile.water.total_subsurface_water() / 10:.1f}L", (hud_x + 10, y_offset), (180, 180, 180))
        y_offset += LINE_HEIGHT

    if tile.wellspring_output > 0:
        draw_text(screen, font, f"Wellspring: {tile.wellspring_output / 10:.2f}L/tick", (hud_x, y_offset), (100, 180, 255))
        y_offset += LINE_HEIGHT

    if tile.trench:
        draw_text(screen, font, "Trench: Yes", (hud_x, y_offset), (180, 180, 120))
        y_offset += LINE_HEIGHT

    if structure:
        draw_text(screen, font, f"Structure: {structure.kind.capitalize()}", (hud_x, y_offset), (120, 200, 120))
        y_offset += LINE_HEIGHT
        if structure.kind == "cistern":
            draw_text(screen, font, f"  Stored: {structure.stored / 10:.1f}L", (hud_x + 10, y_offset), (180, 180, 180))
            y_offset += LINE_HEIGHT
        elif structure.kind == "planter":
            draw_text(screen, font, f"  Growth: {structure.growth}%", (hud_x + 10, y_offset), (180, 180, 180))
            y_offset += LINE_HEIGHT

    return y_offset


def render_inventory(
    screen,
    font,
    state: "GameState",
    pos: Tuple[int, int],
    width: int,
    height: int,
) -> None:
    """Render the inventory panel."""
    inv_x, inv_y = pos
    pygame.draw.rect(screen, (40, 40, 40), (inv_x, inv_y, width, height), 2)

    ix, iy = inv_x + 8, inv_y + 8
    draw_text(screen, font, "Inventory", (ix, iy))
    iy += LINE_HEIGHT

    inv = state.inventory
    draw_text(screen, font, f"Water: {inv.water / 10:.1f}L", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Scrap: {inv.scrap}", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Seeds: {inv.seeds}", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Biomass: {inv.biomass}kg", (ix, iy))


def render_soil_profile(
    screen,
    font,
    tile,
    pos: Tuple[int, int],
    width: int,
    height: int,
) -> None:
    """Render the soil profile visualization."""
    x, y = pos
    terrain, water = tile.terrain, tile.water

    # Draw header and border
    header_y = y - 22
    pygame.draw.rect(screen, (40, 40, 45), (x, header_y, width, height + 22), 0, border_radius=3)
    pygame.draw.rect(screen, (80, 80, 85), (x, header_y, width, height + 22), 1, border_radius=3)
    draw_section_header(screen, font, "Soil Profile", (x + 8, header_y + 5), width=width - 16)

    total_depth = terrain.get_total_soil_depth() + terrain.bedrock_depth
    if total_depth == 0:
        return

    scale = height / total_depth
    current_y = y

    def draw_layer(soil_layer: SoilLayer, label: str):
        nonlocal current_y
        depth = terrain.get_layer_depth(soil_layer)
        if depth == 0:
            return

        layer_height = int(depth * scale)
        if layer_height < 1:
            layer_height = 1

        props = MATERIAL_LIBRARY.get(terrain.get_layer_material(soil_layer))
        color = props.display_color if props else (150, 150, 150)
        layer_rect = pygame.Rect(x + 1, current_y, width - 2, layer_height)
        pygame.draw.rect(screen, color, layer_rect)

        # Draw water fill overlay
        water_in_layer = water.get_layer_water(soil_layer)
        max_storage = terrain.get_max_water_storage(soil_layer)
        if water_in_layer > 0 and max_storage > 0:
            fill_pct = min(100, (water_in_layer * 100) // max_storage)
            water_height = (layer_height * fill_pct) // 100
            if water_height > 0:
                water_rect = pygame.Rect(x + 1, current_y + layer_height - water_height, width - 2, water_height)
                water_surf = pygame.Surface((water_rect.width, water_rect.height), pygame.SRCALPHA)
                water_surf.fill((100, 150, 255, 100))
                screen.blit(water_surf, water_rect.topleft)

        # Draw label if layer is tall enough
        if layer_height >= 16:
            draw_text(screen, font, f"{label[:3]} {units_to_meters(depth):.1f}m", (x + 5, current_y + 2), color=(255, 255, 255))

        current_y += layer_height

    # Draw surface water first, if any
    if water.surface_water > 0:
        surf_height = min(30, int(water.surface_water * scale * 0.5))
        if surf_height > 0:
            surf_rect = pygame.Rect(x + 1, current_y, width - 2, surf_height)
            pygame.draw.rect(screen, (100, 150, 255), surf_rect)
            if surf_height >= 16:
                draw_text(screen, font, f"Water {water.surface_water / 10:.1f}L", (x + 5, current_y + 2), color=(255, 255, 255))
            current_y += surf_height

    # Iterate from top (Organics) to bottom (Bedrock)
    for layer in reversed(SoilLayer):
        draw_layer(layer, layer.name.capitalize())
