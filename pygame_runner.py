# pygame_runner.py
"""
Pygame-CE frontend for the Kemet prototype.

Controls:
- W/A/S/D: move (or menu navigation when menu open)
- 1-9: select tool
- F: use selected tool
- R: open tool options menu
- E: interact with structure/environment
- Space: rest (at night)
- H: show help
- ESC: quit
"""
from __future__ import annotations

import sys
from typing import Dict, List, Tuple

try:
    import pygame
except ImportError as exc:
    raise SystemExit("pygame-ce is required. Install with: pip install pygame-ce") from exc

from main import (
    TILE_TYPES,
    HEAT_NIGHT_THRESHOLD,
    GameState,
    build_initial_state,
    handle_command,
    simulate_tick,
    end_day,
)
from ground import SoilLayer, MATERIAL_LIBRARY, units_to_meters
from tools import get_toolbar, Toolbar
from keybindings import (
    CONTROL_DESCRIPTIONS,
    TOOL_KEYS,
    USE_TOOL_KEY,
    INTERACT_KEY,
    TOOL_MENU_KEY,
    REST_KEY,
    HELP_KEY,
    MENU_UP_KEY,
    MENU_DOWN_KEY,
)
# Import from our new utils file
from utils import clamp

Color = Tuple[int, int, int]
SIDEBAR_WIDTH = 300
TILE_SIZE = 32
LINE_HEIGHT = 20
FONT_SIZE = 18
SECTION_SPACING = 8
MOVE_SPEED = 220
DIAGONAL_FACTOR = 0.707
TICK_INTERVAL = 0.25  # Run a simulation tick every 0.25 seconds for a continuous feel.
PLAYER_RADIUS_DIVISOR = 3
STRUCTURE_INSET = 8
TRENCH_INSET = 10
WELLSPRING_RADIUS = 6
PROFILE_WIDTH = 140
PROFILE_HEIGHT = 240
PROFILE_MARGIN = 10
TOOLBAR_HEIGHT = 32
TOOLBAR_BG_COLOR = (30, 30, 35)
TOOLBAR_SELECTED_COLOR = (60, 55, 40)
TOOLBAR_TEXT_COLOR = (200, 200, 180)
MapSize = Tuple[int, int]
MAP_SIZE: MapSize = (40, 30)

# --- Action Duration System ---
# Defines how long (in seconds) the player is locked while performing an action.
ACTION_DURATIONS = {
    "terrain": 1.0,  # Shovel tool (trench/lower/raise)
    "dig": 1.0,
    "lower": 1.5,
    "raise": 0.8,
    "build": 2.0,
    "collect": 0.5,
    "pour": 0.5,
    "survey": 0.3,
}

BIOME_COLORS: Dict[str, Color] = {"dune": (204, 174, 120), "flat": (188, 158, 112), "wadi": (150, 125, 96),
                                  "rock": (128, 128, 128), "salt": (220, 220, 210)}
ELEVATION_BRIGHTNESS_MIN = 0.7
ELEVATION_BRIGHTNESS_MAX = 1.3
MATERIAL_BLEND_WEIGHT = 0.35
ORGANICS_BLEND_WEIGHT = 0.50


def calculate_elevation_range(state: "GameState") -> Tuple[float, float]:
    elevations = [state.tiles[x][y].elevation for x in range(state.width) for y in range(state.height)]
    return (min(elevations), max(elevations)) if elevations else (0, 0)


def elevation_brightness(elevation: float, min_elev: float, max_elev: float) -> float:
    if max_elev == min_elev: return 1.0
    normalized = (elevation - min_elev) / (max_elev - min_elev)
    return ELEVATION_BRIGHTNESS_MIN + (normalized * (ELEVATION_BRIGHTNESS_MAX - ELEVATION_BRIGHTNESS_MIN))


def apply_brightness(color: Color, brightness: float) -> Color:
    return tuple(max(0, min(255, int(c * brightness))) for c in color)


def blend_colors(color1: Color, color2: Color, weight: float = 0.5) -> Color:
    return tuple(int(c1 * (1 - weight) + c2 * weight) for c1, c2 in zip(color1, color2))


def get_surface_material_color(tile) -> Color | None:
    terrain = tile.terrain
    if terrain.organics_depth > 0:
        props = MATERIAL_LIBRARY.get("humus")
        if props: return props.display_color
    props = MATERIAL_LIBRARY.get(terrain.topsoil_material)
    if props: return props.display_color
    return None


def color_for_tile(state_tile, tile_type, elevation_range: Tuple[float, float]) -> Color:
    if state_tile.hydration >= 10.0: return (48, 133, 214)
    if state_tile.hydration >= 5.0: return (92, 180, 238)
    base_color = BIOME_COLORS.get(tile_type.name, (200, 200, 200))
    material_color = get_surface_material_color(state_tile)
    if material_color:
        weight = ORGANICS_BLEND_WEIGHT if state_tile.terrain.organics_depth > 0 else MATERIAL_BLEND_WEIGHT
        base_color = blend_colors(base_color, material_color, weight)
    min_elev, max_elev = elevation_range
    brightness = elevation_brightness(state_tile.elevation, min_elev, max_elev)
    base_color = apply_brightness(base_color, brightness)
    return base_color


def draw_text(surface, font, text: str, pos: Tuple[int, int], color=(230, 230, 230)) -> None:
    surface.blit(font.render(text, True, color), pos)


def draw_section_header(surface, font, text: str, pos: Tuple[int, int], width: int = 200) -> int:
    x, y = pos
    draw_text(surface, font, text, (x, y), color=(220, 200, 120))
    y += LINE_HEIGHT
    pygame.draw.line(surface, (100, 100, 80), (x, y), (x + width, y), 1)
    return y + 6


def draw_soil_profile(surface, font, tile, pos: Tuple[int, int], width: int, height: int) -> None:
    x, y = pos
    terrain, water = tile.terrain, tile.water

    # Draw header and border
    header_y = y - 22
    pygame.draw.rect(surface, (40, 40, 45), (x, header_y, width, height + 22), 0, border_radius=3)
    pygame.draw.rect(surface, (80, 80, 85), (x, header_y, width, height + 22), 1, border_radius=3)
    draw_section_header(surface, font, "Soil Profile", (x + 8, header_y + 5), width=width - 16)

    total_depth = terrain.get_total_soil_depth() + terrain.bedrock_depth
    if total_depth == 0: return

    scale = height / total_depth
    current_y = y

    def draw_layer(layer: SoilLayer, label: str):
        nonlocal current_y
        depth = terrain.get_layer_depth(layer)
        if depth == 0: return

        layer_height = int(depth * scale)
        if layer_height < 1: layer_height = 1

        props = MATERIAL_LIBRARY.get(terrain.get_layer_material(layer))
        color = props.display_color if props else (150, 150, 150)
        layer_rect = pygame.Rect(x + 1, current_y, width - 2, layer_height)
        pygame.draw.rect(surface, color, layer_rect)

        water_in_layer = water.get_layer_water(layer)
        max_storage = terrain.get_max_water_storage(layer)
        if water_in_layer > 0 and max_storage > 0:
            fill_pct = min(100, (water_in_layer * 100) // max_storage)
            water_height = (layer_height * fill_pct) // 100
            if water_height > 0:
                water_rect = pygame.Rect(x + 1, current_y + layer_height - water_height, width - 2, water_height)
                water_surf = pygame.Surface((water_rect.width, water_rect.height), pygame.SRCALPHA)
                water_surf.fill((100, 150, 255, 100))
                surface.blit(water_surf, water_rect.topleft)

        if layer_height >= 16:
            draw_text(surface, font, f"{label[:3]} {units_to_meters(depth):.1f}m", (x + 5, current_y + 2),
                      color=(255, 255, 255))

        current_y += layer_height

    # Draw surface water first, if any
    if water.surface_water > 0:
        surf_height = min(30, int(water.surface_water * scale * 0.5))  # Make surface water less visually deep
        if surf_height > 0:
            surf_rect = pygame.Rect(x + 1, current_y, width - 2, surf_height)
            pygame.draw.rect(surface, (100, 150, 255), surf_rect)
            if surf_height >= 16:
                draw_text(surface, font, f"Water {water.surface_water / 10:.1f}L", (x + 5, current_y + 2),
                          color=(255, 255, 255))
            current_y += surf_height

    # Iterate from top (Organics) to bottom (Bedrock)
    for layer in reversed(SoilLayer):
        draw_layer(layer, layer.name.capitalize())


def draw_toolbar(surface, font, toolbar: Toolbar, pos: Tuple[int, int], width: int, height: int) -> None:
    x, y = pos
    tools = toolbar.tools
    tool_count = len(tools)
    tool_width = width // tool_count
    pygame.draw.rect(surface, TOOLBAR_BG_COLOR, (x, y, width, height))
    pygame.draw.line(surface, (60, 60, 60), (x, y), (x + width, y), 1)

    for i, tool in enumerate(tools):
        tx = x + (i * tool_width)
        is_selected = (i == toolbar.selected_index)

        # Highlight selected tool
        if is_selected:
            pygame.draw.rect(surface, TOOLBAR_SELECTED_COLOR, (tx + 1, y + 1, tool_width - 2, height - 2))

        # Draw tool number and icon
        draw_text(surface, font, f"{i + 1}", (tx + 4, y + 2), color=(150, 150, 130))
        draw_text(surface, font, tool.icon, (tx + 18, y + 2), color=TOOLBAR_TEXT_COLOR)

        # Show current option for tools with menus, or tool name
        if tool.has_menu() and is_selected:
            opt = tool.get_current_option()
            label = opt.name[:6] if opt else tool.name[:6]
            draw_text(surface, font, label, (tx + 4, y + 16), color=(180, 180, 140))
        else:
            draw_text(surface, font, tool.name[:6], (tx + 4, y + 16), color=(140, 140, 140))

        # Separator
        if i < tool_count - 1:
            pygame.draw.line(surface, (50, 50, 50), (tx + tool_width - 1, y + 4), (tx + tool_width - 1, y + height - 4), 1)


def draw_help_overlay(surface, font, controls: List[str], pos: Tuple[int, int], available_width: int,
                      available_height: int) -> None:
    x, y = pos
    col_width, row_height = 130, 18
    cols = max(1, available_width // col_width)
    pygame.draw.rect(surface, (25, 25, 30), (x - 4, y - 4, available_width, available_height), 0)
    draw_text(surface, font, "CONTROLS", (x, y), color=(220, 200, 120))
    y += row_height + 4
    for i, control in enumerate(controls):
        cx, cy = x + (i % cols * col_width), y + (i // cols * row_height)
        if cy + row_height < pos[1] + available_height:
            draw_text(surface, font, control, (cx, cy), color=(180, 180, 160))


def render(screen, font, state: GameState, tile_size: int, player_px: Tuple[float, float], toolbar: Toolbar,
           show_help: bool, elevation_range: Tuple[float, float]) -> None:
    screen.fill((20, 20, 25))
    map_width, map_height = state.width * tile_size, state.height * tile_size
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            color = color_for_tile(tile, TILE_TYPES[tile.kind], elevation_range)
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            pygame.draw.rect(screen, color, rect)
            if tile.trench:
                pygame.draw.rect(screen, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))
    for (x, y), structure in state.structures.items():
        rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
        pygame.draw.rect(screen, (30, 30, 30), rect.inflate(-STRUCTURE_INSET, -STRUCTURE_INSET))
        draw_text(screen, font, structure.kind[0].upper(), (rect.x + 6, rect.y + 4))
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            if tile.wellspring_output > 0:
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(screen, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))

    # Draw player and action timer bar
    player_center_x, player_center_y = int(player_px[0]), int(player_px[1])
    pygame.draw.circle(screen, (240, 240, 90), (player_center_x, player_center_y),
                       tile_size // PLAYER_RADIUS_DIVISOR)
    if state.player_action_timer > 0:
        bar_width = tile_size
        bar_height = 4
        bar_x = player_center_x - bar_width // 2
        bar_y = player_center_y - tile_size // 2 - bar_height - 2

        action_duration = ACTION_DURATIONS.get(state.last_action, 1.0)
        progress = state.player_action_timer / action_duration

        pygame.draw.rect(screen, (50, 50, 50), (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(screen, (200, 200, 80), (bar_x, bar_y, int(bar_width * progress), bar_height))

    hud_x, y_offset = map_width + 12, 12
    y_offset = draw_section_header(screen, font, "ENVIRONMENT", (hud_x, y_offset)) + 4
    draw_text(screen, font, f"Day: {state.day}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Time: {'Night' if state.is_night else 'Day'}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Heat: {state.heat}%", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    draw_text(screen, font, f"Rain: {'Active' if state.raining else f'in {state.rain_timer}t'}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT + SECTION_SPACING
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
    draw_text(screen, font, f"  Surface: {tile.water.surface_water / 10:.1f}L", (hud_x + 10, y_offset),
              (180, 180, 180))
    y_offset += LINE_HEIGHT
    if tile.water.total_subsurface_water() > 0:
        draw_text(screen, font, f"  Ground: {tile.water.total_subsurface_water() / 10:.1f}L", (hud_x + 10, y_offset),
                  (180, 180, 180))
        y_offset += LINE_HEIGHT
    if tile.wellspring_output > 0:
        draw_text(screen, font, f"Wellspring: {tile.wellspring_output / 10:.2f}L/tick", (hud_x, y_offset),
                  (100, 180, 255))
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

    soil_x, soil_y = screen.get_width() - PROFILE_WIDTH - PROFILE_MARGIN, 12
    draw_soil_profile(screen, font, tile, (soil_x, soil_y + 22), PROFILE_WIDTH, PROFILE_HEIGHT - 22)

    inv_w, inv_h = 180, 140
    inv_x, inv_y = screen.get_width() - inv_w - 12, clamp(map_height - inv_h - 12, 12, 9999)
    pygame.draw.rect(screen, (40, 40, 40), (inv_x, inv_y, inv_w, inv_h), 2)
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
    night_alpha = max(0, min(200, int((140 - state.heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface((map_width, map_height), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        screen.blit(overlay, (0, 0))
    draw_toolbar(screen, font, toolbar, (0, map_height), map_width, TOOLBAR_HEIGHT)
    log_panel_y = map_height + TOOLBAR_HEIGHT
    log_panel_height = screen.get_height() - log_panel_y
    pygame.draw.line(screen, (80, 80, 80), (0, log_panel_y), (screen.get_width(), log_panel_y), 2)
    log_x, log_y = 12, log_panel_y + 8
    if show_help:
        draw_help_overlay(screen, font, CONTROL_DESCRIPTIONS, (log_x, log_y), screen.get_width() - 24,
                          log_panel_height - 16)
    else:
        draw_text(screen, font, "EVENT LOG", (log_x, log_y), color=(200, 180, 120))
        log_y += LINE_HEIGHT + 4
        max_messages = (log_panel_height - 40) // 18
        for msg in state.messages[-max_messages:]:
            draw_text(screen, font, f"• {msg}", (log_x, log_y), color=(160, 200, 160))
            log_y += 18


def issue(state: GameState, cmd: str, args: List[str]) -> None:
    """Issues a command and sets the player's action timer."""
    if state.player_action_timer > 0:
        return  # Player is busy

    # Handle special case for resting
    if cmd == "end":
        end_day(state)
        return

    if handle_command(state, cmd, args):
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        return

    # Set the action timer if the command has a duration
    duration = ACTION_DURATIONS.get(cmd)
    if duration:
        state.player_action_timer = duration
        state.last_action = cmd


def update_player_position(state: GameState, player_px: List[float], vel: Tuple[float, float], dt: float,
                           tile_size: int) -> None:
    if state.player_action_timer > 0:
        return  # Player is busy

    if vel == (0.0, 0.0): return
    vx, vy = vel
    if vx != 0.0 and vy != 0.0:
        vx *= DIAGONAL_FACTOR
        vy *= DIAGONAL_FACTOR
    new_x = clamp(player_px[0] + vx * dt, 0, state.width * tile_size - 1)
    new_y = clamp(player_px[1] + vy * dt, 0, state.height * tile_size - 1)
    target_tile_x, target_tile_y = int(new_x // tile_size), int(new_y // tile_size)
    if state.tiles[target_tile_x][target_tile_y].kind == "rock":
        current_tile_x, current_tile_y = int(player_px[0] // tile_size), int(player_px[1] // tile_size)
        if (target_tile_x, target_tile_y) != (current_tile_x, current_tile_y):
            if (target_tile_x, target_tile_y) != state.last_rock_blocked:
                state.messages.append("Rock blocks the way.")
                state.last_rock_blocked = (target_tile_x, target_tile_y)
            return
    player_px[0], player_px[1] = new_x, new_y
    state.player = (target_tile_x, target_tile_y)


def run(window_size: MapSize = MAP_SIZE, tile_size: int = TILE_SIZE) -> None:
    pygame.init()
    map_w, map_h = window_size
    window_width = map_w * tile_size + SIDEBAR_WIDTH
    window_height = map_h * tile_size + TOOLBAR_HEIGHT + 120
    screen = pygame.display.set_mode((window_width, window_height))
    pygame.display.set_caption("Kemet - Desert Terraforming")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Welcome to Kemet. Press H for help. 1-9 select tools, F to use, R for options, E to interact.")
    player_px = [state.player[0] * tile_size + tile_size / 2, state.player[1] * tile_size + tile_size / 2]
    tick_timer = 0.0
    toolbar = get_toolbar()
    show_help = False
    elevation_range = calculate_elevation_range(state)
    running = True
    while running:
        dt = clock.tick(60) / 1000.0

        # Handle player action timer
        if state.player_action_timer > 0:
            state.player_action_timer = max(0, state.player_action_timer - dt)

        # Handle Inputs
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN:
                # Help toggle works even when busy
                if event.key == HELP_KEY:
                    show_help = not show_help
                    toolbar.close_menu()
                    continue

                # Tool menu navigation when menu is open
                if toolbar.menu_open:
                    if event.key == MENU_UP_KEY:
                        toolbar.cycle_menu_option(-1)
                        continue
                    elif event.key == MENU_DOWN_KEY:
                        toolbar.cycle_menu_option(1)
                        continue
                    elif event.key == TOOL_MENU_KEY:
                        toolbar.close_menu()
                        continue
                    elif event.key == USE_TOOL_KEY:
                        # Select option and use tool
                        toolbar.close_menu()
                        # Fall through to use tool below

                # Tool selection works even when busy (closes menu)
                if event.key in TOOL_KEYS:
                    tool_num = TOOL_KEYS[event.key]
                    toolbar.select_by_number(tool_num)
                    continue

                # Block other actions while busy
                if state.player_action_timer > 0:
                    continue

                if event.key == REST_KEY:
                    issue(state, "end", [])
                elif event.key == TOOL_MENU_KEY:
                    # R key: toggle tool options menu
                    tool = toolbar.get_selected_tool()
                    if tool and tool.has_menu():
                        toolbar.toggle_menu()
                    else:
                        state.messages.append("This tool has no options.")
                elif event.key == INTERACT_KEY:
                    # E key: interact (collect/resupply)
                    issue(state, "collect", [])
                elif event.key == USE_TOOL_KEY:
                    # F key: use selected tool
                    tool = toolbar.get_selected_tool()
                    if tool:
                        action, args = tool.get_action()
                        issue(state, action, args)
                        if action in ("terrain", "raise", "lower"):
                            elevation_range = calculate_elevation_range(state)

        # Handle continuous movement (disabled when menu is open)
        if not toolbar.menu_open:
            keys = pygame.key.get_pressed()
            vx = vy = 0.0
            if keys[pygame.K_w]: vy -= MOVE_SPEED
            if keys[pygame.K_s]: vy += MOVE_SPEED
            if keys[pygame.K_a]: vx -= MOVE_SPEED
            if keys[pygame.K_d]: vx += MOVE_SPEED
            update_player_position(state, player_px, (vx, vy), dt, tile_size)

        # Continuous world simulation tick
        tick_timer += dt
        if tick_timer >= TICK_INTERVAL:
            simulate_tick(state)
            tick_timer -= TICK_INTERVAL

        render(screen, font, state, tile_size, tuple(player_px), toolbar, show_help, elevation_range)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
