# render/hud.py
"""HUD panels: environment info, tile info, inventory, soil profile."""
from __future__ import annotations

import math
import numpy as np
from typing import TYPE_CHECKING, Tuple

import pygame

from config import DAY_LENGTH
from ground import SoilLayer, MATERIAL_LIBRARY, units_to_meters
from render.primitives import draw_text, draw_section_header
from render.config import (
    LINE_HEIGHT,
    SECTION_SPACING,
    COLOR_BORDER,
    COLOR_BORDER_LIGHT,
    COLOR_BG_PANEL,
    COLOR_TEXT_GRAY,
    COLOR_TEXT_WHITE,
    COLOR_WELLSPRING_STRONG,
    COLOR_TRENCH,
    COLOR_WATER_DEEP,
    COLOR_SKY,
    METER_SCALE,
)
from subgrid import tile_to_subgrid

if TYPE_CHECKING:
    from main import GameState


def get_time_string(state: "GameState") -> str:
    """Formats the current game time into a string."""
    if state.is_night:
        return f"Day {state.day} (Night)"

    if DAY_LENGTH <= 0:
        return f"Day {state.day}"

    day_progress = state.turn_in_day / DAY_LENGTH
    # Map 0.0-1.0 progress to 12 hours of daylight (e.g., 6:00 to 18:00)
    total_daylight_minutes = 12 * 60
    current_minute_of_daylight = int(day_progress * total_daylight_minutes)

    start_hour = 6
    hour = start_hour + (current_minute_of_daylight // 60)
    minute = current_minute_of_daylight % 60

    return f"Day {state.day}, {hour:02d}:{minute:02d}"


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
    y_offset = draw_section_header(screen, font, "ENVIRONMENT", (hud_x, y_offset), width=130) + 4
    time_str = get_time_string(state)
    draw_text(screen, font, time_str, (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Heat: {state.heat}%", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Rain: {'Active' if state.raining else f'in {state.rain_timer}t'}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT + SECTION_SPACING

    # Atmosphere Section (grid-based)
    # NEW: Grid-based atmosphere at cursor position
    if state.humidity_grid is not None and state.wind_grid is not None:
        # Use cursor position (target_subsquare), fallback to player position
        if state.target_subsquare is not None:
            sx, sy = state.target_subsquare
        else:
            sx, sy = state.player_subsquare

        y_offset = draw_section_header(screen, font, "ATMOSPHERE", (hud_x, y_offset), width=130) + 4

        # Humidity at cursor
        humidity = state.humidity_grid[sx, sy]
        draw_text(screen, font, f"Humidity: {humidity*100:.0f}%", (hud_x, y_offset))
        y_offset += LINE_HEIGHT

        # Wind at cursor (calculate angle for arrow)
        wind_x = state.wind_grid[sx, sy, 0]
        wind_y = state.wind_grid[sx, sy, 1]
        wind_magnitude = float(np.sqrt(wind_x**2 + wind_y**2))

        if wind_magnitude > 0.01:
            wind_angle = np.arctan2(wind_y, wind_x)
            # Convert to compass: 0° = east, counter-clockwise
            # Adjust to: 0° = N, 90° = E, 180° = S, 270° = W
            compass_deg = (90 - np.degrees(wind_angle)) % 360
            arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖']
            arrow_idx = int((compass_deg + 22.5) / 45) % 8
            arrow = arrows[arrow_idx]
        else:
            arrow = '·'  # Calm wind indicator

        draw_text(screen, font, f"Wind: {arrow} {wind_magnitude*100:.0f}", (hud_x, y_offset))
        y_offset += LINE_HEIGHT + SECTION_SPACING

    # LEGACY: Fall back to old atmosphere system during transition
    elif state.atmosphere:
        x, y = state.player
        region = state.atmosphere.get_region_at_tile(x, y)

        y_offset = draw_section_header(screen, font, "ATMOSPHERE", (hud_x, y_offset), width=130) + 4

        # Humidity
        draw_text(screen, font, f"Humidity: {region.humidity*100:.0f}%", (hud_x, y_offset))
        y_offset += LINE_HEIGHT

        # Wind
        arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖']
        idx = region.wind_direction % 8
        draw_text(screen, font, f"Wind: {arrows[idx]} {region.wind_speed*100:.0f}", (hud_x, y_offset))
        y_offset += LINE_HEIGHT + SECTION_SPACING

    # Current tile section
    x, y = state.player
    # Check for structure at player's sub-square position
    player_sub = state.player_subsquare
    structure = state.structures.get(player_sub)
    sx, sy = player_sub

    y_offset = draw_section_header(screen, font, "CURRENT TILE", (hud_x, y_offset), width=130) + 4
    draw_text(screen, font, f"Position: ({x}, {y})", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    tile_kind = state.get_tile_kind(x, y)
    draw_text(screen, font, f"Type: {tile_kind.capitalize()}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT

    # Get exposed material from grid
    from render.grid_helpers import get_exposed_material, get_grid_elevation
    from ground import units_to_meters
    material = get_exposed_material(state, sx, sy)
    draw_text(screen, font, f"Material: {material.capitalize()}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT

    elevation_units = get_grid_elevation(state, sx, sy)
    draw_text(screen, font, f"Elevation: {units_to_meters(elevation_units):.2f}m", (hud_x, y_offset))
    y_offset += LINE_HEIGHT

    if state.moisture_grid is not None:
        # Aggregate from grid resolution to tile
        from config import SUBGRID_SIZE
        gx_start, gy_start = x * SUBGRID_SIZE, y * SUBGRID_SIZE
        tile_moisture_cells = state.moisture_grid[
            gx_start:gx_start + SUBGRID_SIZE,
            gy_start:gy_start + SUBGRID_SIZE
        ]
        moist = tile_moisture_cells.mean()
        # Light blue for moisture
        draw_text(screen, font, f"Soil Moisture: {moist:.1f}", (hud_x, y_offset), (100, 200, 255))
    y_offset += LINE_HEIGHT
    # Get water from grids
    gx_start, gy_start = x * SUBGRID_SIZE, y * SUBGRID_SIZE
    surface_water = state.water_grid[gx_start:gx_start+SUBGRID_SIZE, gy_start:gy_start+SUBGRID_SIZE].sum()
    # Get subsurface water from grid (sum all 9 grid cells for this tile, all layers)
    tile_subsurface = state.subsurface_water_grid[
        :,  # All layers
        gx_start:gx_start + SUBGRID_SIZE,
        gy_start:gy_start + SUBGRID_SIZE
    ].sum()
    total_water = surface_water + tile_subsurface
    draw_text(screen, font, f"Water: {total_water / 10:.1f}L total", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"  Surface: {surface_water / 10:.1f}L", (hud_x + 10, y_offset), COLOR_TEXT_GRAY)
    y_offset += LINE_HEIGHT

    if tile_subsurface > 0:
        draw_text(screen, font, f"  Ground: {tile_subsurface / 10:.1f}L", (hud_x + 10, y_offset), COLOR_TEXT_GRAY)
        y_offset += LINE_HEIGHT

    # Check if any subsquare in the player's tile has a trench
    sx_base, sy_base = tile_to_subgrid(x, y)
    if state.trench_grid is not None and np.any(state.trench_grid[sx_base:sx_base+3, sy_base:sy_base+3]):
        draw_text(screen, font, "Trench: Yes", (hud_x, y_offset), COLOR_TRENCH)
        y_offset += LINE_HEIGHT

    # Check wellspring from grid (center cell of tile)
    center_sx, center_sy = gx_start + 1, gy_start + 1
    wellspring_output = state.wellspring_grid[center_sx, center_sy] if state.wellspring_grid is not None else 0
    if wellspring_output > 0:
        draw_text(screen, font, f"Wellspring: {wellspring_output / 10:.2f}L/tick", (hud_x, y_offset), COLOR_WELLSPRING_STRONG)
        y_offset += LINE_HEIGHT

    if structure:
        draw_text(screen, font, f"Structure: {structure.kind.capitalize()}", (hud_x, y_offset), (120, 200, 120))
        y_offset += LINE_HEIGHT
        if structure.kind == "cistern":
            draw_text(screen, font, f"  Stored: {structure.stored / 10:.1f}L", (hud_x + 10, y_offset), COLOR_TEXT_GRAY)
            y_offset += LINE_HEIGHT
        elif structure.kind == "planter":
            draw_text(screen, font, f"  Growth: {structure.growth}%", (hud_x + 10, y_offset), COLOR_TEXT_GRAY)
            y_offset += LINE_HEIGHT

    return y_offset


def render_inventory(
    screen,
    font,
    state: "GameState",
    x: int,
    y: int,
) -> int:
    """Render the inventory as a text section. Returns new y position."""
    ix, iy = x, y

    iy = draw_section_header(screen, font, "INVENTORY", (ix, iy), width=130) + 4

    inv = state.inventory
    draw_text(screen, font, f"Water: {inv.water / 10:.1f}L", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Scrap: {inv.scrap}", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Seeds: {inv.seeds}", (ix, iy))
    iy += LINE_HEIGHT
    draw_text(screen, font, f"Biomass: {inv.biomass}kg", (ix, iy))
    
    return iy + LINE_HEIGHT + SECTION_SPACING


def render_soil_profile(
    screen,
    font,
    state: "GameState",
    sx: int,
    sy: int,
    pos: Tuple[int, int],
    width: int,
    height: int,
    surface_water: int = 0,
) -> None:
    """Render the soil profile visualization for a grid cell (array-based).

    Shows terrain layers, water, and elevation from grids.
    Includes an elevation gauge on the left showing depth relative to sea level.

    Args:
        state: Game state with grids
        sx, sy: Grid cell coordinates
        surface_water: Surface water amount (from water_grid)
    """
    x, y = pos

    # Get elevation components from grids
    bedrock = state.bedrock_base[sx, sy]

    # Calculate surface elevation: bedrock + sum of layers
    surface_elev = bedrock + np.sum(state.terrain_layers[:, sx, sy])

    # Layout: gauge on left (40px), soil profile on right
    gauge_width = 40
    profile_x = x + gauge_width
    profile_width = width - gauge_width


    # Define view transform: Sea level (0m) is at center of content area
    center_y = y + height // 2
    
    def elev_to_y(elev_m: float) -> int:
        """Convert elevation in meters to screen Y coordinate."""
        # Y grows down, so positive elevation is up (negative Y offset)
        return int(center_y - (elev_m * METER_SCALE))

    # Set clip rect to ensure drawing stays within content area
    content_rect = pygame.Rect(x, y, width, height)
    original_clip = screen.get_clip()
    screen.set_clip(content_rect)

    # --- 1. Draw Sky ---
    # Sky goes from top of panel down to surface elevation
    # Note: surface_elev already includes offset_units, so don't add offset_m again
    surface_m = units_to_meters(surface_elev)
    surface_y = elev_to_y(surface_m)
    
    # Draw sky background
    if surface_y > y:
        sky_rect = pygame.Rect(profile_x, y, profile_width, surface_y - y)
        pygame.draw.rect(screen, COLOR_SKY, sky_rect)

    # --- 2. Draw Layers (from grids) ---
    # Calculate cumulative elevations for layers
    layer_bottoms = {}
    cumulative = bedrock
    layer_bottoms[SoilLayer.BEDROCK] = bedrock
    # Add bedrock depth to cumulative so other layers stack on top of it
    cumulative += state.terrain_layers[SoilLayer.BEDROCK, sx, sy]
    for layer in SoilLayer:
        if layer != SoilLayer.BEDROCK:
            layer_bottoms[layer] = cumulative
            cumulative += state.terrain_layers[layer, sx, sy]

    # Iterate layers from top (Organics) to bottom (Bedrock)
    for layer in reversed(SoilLayer):
        depth = state.terrain_layers[layer, sx, sy]
        if depth == 0 and layer != SoilLayer.BEDROCK:
            continue

        # Get layer range in absolute meters (relative to sea level)
        bot_units = layer_bottoms[layer]
        top_units = bot_units + depth
        top_m = units_to_meters(top_units)
        bot_m = units_to_meters(bot_units)

        # For bedrock, extend visually to bottom of panel
        if layer == SoilLayer.BEDROCK:
            bot_m = -100.0  # Arbitrary deep value

        layer_top_y = elev_to_y(top_m)
        layer_bot_y = elev_to_y(bot_m)

        # Skip if off screen
        if layer_bot_y < y or layer_top_y > y + height:
            continue

        # Clamp to panel
        draw_top = max(y, layer_top_y)
        draw_h = min(y + height, layer_bot_y) - draw_top

        if draw_h > 0:
            material_name = state.terrain_materials[layer, sx, sy]
            # Handle empty/uninitialized material names
            if not material_name or material_name == '':
                # Use default gray for missing material
                color = (150, 150, 150)
            else:
                props = MATERIAL_LIBRARY.get(material_name)
                color = props.display_color if props else (150, 150, 150)
            pygame.draw.rect(screen, color, (profile_x, draw_top, profile_width, draw_h))

            # Draw water fill overlay from grids
            water_in_layer = state.subsurface_water_grid[layer, sx, sy]
            porosity = state.porosity_grid[layer, sx, sy]
            max_storage = (depth * porosity) // 100
            if water_in_layer > 0 and max_storage > 0:
                fill_pct = min(100, (water_in_layer * 100) // max_storage)
                # Water fills from bottom of layer up
                water_h = int((layer_bot_y - layer_top_y) * fill_pct / 100)
                water_top = layer_bot_y - water_h

                # Clamp water rect
                w_draw_top = max(y, water_top)
                w_draw_bot = min(y + height, layer_bot_y)
                if w_draw_bot > w_draw_top:
                    water_surf = pygame.Surface((profile_width, w_draw_bot - w_draw_top), pygame.SRCALPHA)
                    water_surf.fill((40, 80, 160, 150))
                    screen.blit(water_surf, (profile_x, w_draw_top))

            # Label
            if draw_h >= 16:
                draw_text(screen, font, f"{layer.name.capitalize()[:3]}", (profile_x + 4, draw_top + 2), color=COLOR_TEXT_WHITE)

            # Draw separator line at the bottom of the layer
            if layer != SoilLayer.BEDROCK:
                if y <= layer_bot_y < y + height:
                    pygame.draw.line(screen, (0, 0, 0), (profile_x, layer_bot_y), (profile_x + profile_width, layer_bot_y), 1)

    # --- 3. Draw Surface Water ---
    if surface_water > 0:
        water_depth_m = units_to_meters(surface_water)
        water_top_y = elev_to_y(surface_m + water_depth_m)
        water_h = surface_y - water_top_y
        if water_h > 0:
            pygame.draw.rect(screen, (50, 100, 200), (profile_x, water_top_y, profile_width, water_h))

    # --- 4. Draw Gauge ---
    # Restore clip for gauge (or keep it clipped to content area)
    # Draw gauge background
    pygame.draw.rect(screen, COLOR_BG_PANEL, (x, y, gauge_width, height))

    gauge_x = x + 2
    gauge_line_x = x + gauge_width - 8
    pygame.draw.line(screen, (120, 120, 130), (gauge_line_x, y), (gauge_line_x, y + height), 1)

    # Calculate visible meter range
    # Top of panel is y, which corresponds to some elevation
    # y = center_y - elev * scale  =>  elev = (center_y - y) / scale
    max_visible_m = math.ceil((center_y - y) / METER_SCALE)
    min_visible_m = math.floor((center_y - (y + height)) / METER_SCALE)

    for m in range(min_visible_m, max_visible_m + 1):
        tick_y = elev_to_y(m)
        if tick_y < y or tick_y > y + height:
            continue
            
        # Major tick for 0 (Sea Level)
        if m == 0:
            pygame.draw.line(screen, (100, 150, 255), (gauge_line_x - 8, tick_y), (gauge_line_x + profile_width, tick_y), 1)
            draw_text(screen, font, "0", (gauge_x + 8, tick_y - 6), color=(100, 150, 255))
        else:
            # Standard tick
            pygame.draw.line(screen, (150, 150, 160), (gauge_line_x - 4, tick_y), (gauge_line_x, tick_y), 1)
            if m % 2 == 0: # Label even meters
                draw_text(screen, font, f"{m}", (gauge_x, tick_y - 6), color=(150, 150, 160))

    # Restore clip
    screen.set_clip(original_clip)

    # --- 5. Draw Header & Border (Last to ensure Z-order on top) ---
    header_y = y - 22
    # Draw background for header only (to cover any sky bleeding up)
    pygame.draw.rect(screen, COLOR_BG_PANEL, (x, header_y, width, 22), 0, border_radius=3)
    # Draw border around entire panel
    pygame.draw.rect(screen, COLOR_BORDER_LIGHT, (x, header_y, width, height + 22), 1, border_radius=3)
    header_text = f"Elev: {units_to_meters(surface_elev):.1f}m"
    draw_section_header(screen, font, header_text, (x + 8, header_y + 2), width=width - 16)
