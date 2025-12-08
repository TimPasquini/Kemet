"""
Pygame-CE frontend for the Kemet prototype.
Controls (while window focused):
- W/A/S/D: move
- T: dig trench
- Z: lower ground
- X: raise ground
- C: build cistern
- N: build condenser
- P: build planter
- E: collect water on tile
- F: pour 1L water on tile
- V: survey tile
- SPACE: end day
- H: show help in log
- ESC or close window: quit
"""
from __future__ import annotations

import sys
from typing import List, Tuple

try:
    import pygame
except ImportError as exc:  # pragma: no cover - pygame import guard
    raise SystemExit(
        "pygame-ce is required. Install with: pip install pygame-ce"
    ) from exc

from main import (
    TILE_TYPES,
    HEAT_NIGHT_THRESHOLD,
    clamp,
    GameState,
    build_initial_state,
    handle_command,
    simulate_tick,
)
from ground import SoilLayer, MATERIAL_LIBRARY, units_to_meters

# Display constants
SIDEBAR_WIDTH = 300
TILE_SIZE = 32
LINE_HEIGHT = 20
FONT_SIZE = 18
SECTION_SPACING = 8

# Movement and collision constants
MOVE_SPEED = 220  # pixels per second
DIAGONAL_FACTOR = 0.707  # 1/sqrt(2) for normalized diagonal movement

# Rendering constants
TICK_INTERVAL = 0.7  # seconds per simulation tick
PLAYER_RADIUS_DIVISOR = 3
STRUCTURE_INSET = 8
TRENCH_INSET = 10
WELL_RADIUS = 6

# Profile meter constants
PROFILE_WIDTH = 180
PROFILE_HEIGHT = 300
PROFILE_MARGIN = 10

# Control scheme - single source of truth
CONTROLS = [
    "WASD: move",
    "T: dig trench",
    "Z: lower ground",
    "X: raise ground",
    "C: build cistern",
    "N: build condenser",
    "P: build planter",
    "E: collect water",
    "F: pour 1L",
    "V: survey",
    "Space: end day",
    "H: help",
    "Esc: quit"
]

MapSize = Tuple[int, int]


def color_for_tile(state_tile, tile_type) -> Tuple[int, int, int]:
    """
    Determine the display color for a tile based on hydration and terrain type.
    
    Prioritizes water visualization over base terrain color.
    """
    # Hydration overlays
    if state_tile.hydration >= 10.0:
        return (48, 133, 214)  # deep water
    if state_tile.hydration >= 5.0:
        return (92, 180, 238)  # damp
    # Base per tile kind
    return {
        "dune": (204, 174, 120),
        "flat": (188, 158, 112),
        "wadi": (150, 125, 96),
        "rock": (128, 128, 128),
        "salt": (220, 220, 210),
    }.get(tile_type.name, (200, 200, 200))


def draw_text(surface, font, text: str, pos: Tuple[int, int], color=(230, 230, 230)) -> None:
    """Render text at the specified position."""
    surface.blit(font.render(text, True, color), pos)


def draw_section_header(surface, font, text: str, pos: Tuple[int, int]) -> int:
    """Draw a section header with underline. Returns new y position."""
    x, y = pos
    draw_text(surface, font, text, (x, y), color=(220, 200, 120))
    y += LINE_HEIGHT
    pygame.draw.line(surface, (100, 100, 80), (x, y), (x + 200, y), 1)
    return y + 6


def draw_soil_profile(surface, font, tile, pos: Tuple[int, int], width: int, height: int) -> None:
    """
    Draw a cross-section view of the soil layers for the current tile.
    
    Shows layers from surface down to bedrock with proper scaling and colors.
    """
    x, y = pos
    terrain = tile.terrain
    water = tile.water
    
    # Draw border
    pygame.draw.rect(surface, (100, 100, 100), (x, y, width, height), 2)
    
    # Draw title
    draw_text(surface, font, "Soil Profile", (x + 5, y - 18), color=(200, 200, 200))
    
    # Calculate total height and scale
    total_depth = terrain.get_total_soil_depth() + terrain.bedrock_depth
    if total_depth == 0:
        return
    
    scale = (height - 20) / total_depth  # pixels per unit
    
    current_y = y + 10
    
    # Helper to draw a layer
    def draw_layer(layer: SoilLayer, label: str):
        nonlocal current_y
        depth = terrain.get_layer_depth(layer)
        if depth == 0:
            return
        
        layer_height = int(depth * scale)
        if layer_height < 2:  # Too thin to show
            return
        
        material = terrain.get_layer_material(layer)
        props = MATERIAL_LIBRARY.get(material)
        color = props.display_color if props else (150, 150, 150)
        
        # Draw material
        layer_rect = pygame.Rect(x + 5, current_y, width - 10, layer_height)
        pygame.draw.rect(surface, color, layer_rect)
        pygame.draw.rect(surface, (80, 80, 80), layer_rect, 1)
        
        # Draw water overlay if present
        water_in_layer = water.get_layer_water(layer)
        max_storage = terrain.get_max_water_storage(layer)
        if water_in_layer > 0 and max_storage > 0:
            fill_pct = min(100, (water_in_layer * 100) // max_storage)
            water_height = (layer_height * fill_pct) // 100
            if water_height > 1:
                water_rect = pygame.Rect(
                    x + 5,
                    current_y + layer_height - water_height,
                    width - 10,
                    water_height
                )
                water_surf = pygame.Surface((water_rect.width, water_rect.height), pygame.SRCALPHA)
                water_surf.fill((100, 150, 255, 100))
                surface.blit(water_surf, water_rect.topleft)
        
        # Draw label if layer is tall enough
        if layer_height >= 16:
            label_text = f"{label[:3]} {units_to_meters(depth):.1f}m"
            draw_text(surface, font, label_text, (x + 8, current_y + 2), color=(255, 255, 255))
        
        current_y += layer_height
    
    # Draw layers from top to bottom
    # Surface water
    if water.surface_water > 0:
        surf_height = min(30, int(water.surface_water * scale))
        if surf_height > 2:
            surf_rect = pygame.Rect(x + 5, current_y, width - 10, surf_height)
            pygame.draw.rect(surface, (100, 150, 255), surf_rect)
            if surf_height >= 16:
                draw_text(surface, font, f"Water {water.surface_water/10:.1f}L", 
                         (x + 8, current_y + 2), color=(255, 255, 255))
            current_y += surf_height
    
    draw_layer(SoilLayer.ORGANICS, "Organics")
    draw_layer(SoilLayer.TOPSOIL, "Topsoil")
    draw_layer(SoilLayer.ELUVIATION, "Eluviation")
    draw_layer(SoilLayer.SUBSOIL, "Subsoil")
    draw_layer(SoilLayer.REGOLITH, "Regolith")
    draw_layer(SoilLayer.BEDROCK, "Bedrock")


def render(screen, font, state: GameState, tile_size: int, sidebar: int, player_px: Tuple[float, float]) -> None:
    """
    Render the complete game state to the pygame window.
    
    Draws tiles, structures, player, HUD sidebar with inventory and soil profile.
    Log messages displayed in bottom panel across full width.
    """
    screen.fill((20, 20, 25))
    
    map_width = state.width * tile_size
    map_height = state.height * tile_size
    
    # Draw tiles
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            color = color_for_tile(tile, ttype)
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            pygame.draw.rect(screen, color, rect)
            if tile.trench:
                pygame.draw.rect(screen, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))
    
    # Draw structures
    for (x, y), structure in state.structures.items():
        rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
        pygame.draw.rect(screen, (30, 30, 30), rect.inflate(-STRUCTURE_INSET, -STRUCTURE_INSET))
        label = {"cistern": "C", "condenser": "N", "planter": "P"}.get(structure.kind, "?")
        draw_text(screen, font, label, (rect.x + 6, rect.y + 4))
    
    # Draw wells and depot markers
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            if tile.well_output > 0:
                # Different colors for seep vs spring (converting units to L for comparison)
                well_color = (100, 180, 240) if tile.well_output/10 > 0.3 else (70, 140, 220)
                pygame.draw.circle(screen, well_color, rect.center, WELL_RADIUS)
            if tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))
    
    # Draw player (use sub-tile pixel position for smooth movement)
    px, py = player_px
    pygame.draw.circle(screen, (240, 240, 90), (int(px), int(py)), tile_size // PLAYER_RADIUS_DIVISOR)
    
    # Sidebar HUD
    hud_x = map_width + 12
    y_offset = 12
    
    # Environment section
    y_offset = draw_section_header(screen, font, "ENVIRONMENT", (hud_x, y_offset))
    y_offset += 4
    
    draw_text(screen, font, f"Day: {state.day}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    phase = "Night" if state.heat < HEAT_NIGHT_THRESHOLD else "Day"
    draw_text(screen, font, f"Time: {phase}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Heat: {state.heat}%", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    rain_status = "Active" if state.raining else f"in {state.rain_timer}t"
    draw_text(screen, font, f"Rain: {rain_status}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT + SECTION_SPACING
    
    # Inventory section
    y_offset = draw_section_header(screen, font, "INVENTORY", (hud_x, y_offset))
    y_offset += 4
    
    inv = state.inventory
    draw_text(screen, font, f"Water: {inv['water']/10:.1f}L", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Scrap: {int(inv['scrap'])} units", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Seeds: {int(inv['seeds'])} units", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Biomass: {int(inv['biomass'])} kg", (hud_x, y_offset))
    y_offset += LINE_HEIGHT + SECTION_SPACING
    
    # Current tile section
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))
    
    y_offset = draw_section_header(screen, font, "CURRENT TILE", (hud_x, y_offset))
    y_offset += 4
    
    draw_text(screen, font, f"Position: ({x}, {y})", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Type: {tile.kind.capitalize()}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Elevation: {tile.elevation:.2f}m", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    total_water = tile.water.total_water()
    draw_text(screen, font, f"Water: {total_water/10:.1f}L total", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    surface_water = tile.water.surface_water
    draw_text(screen, font, f"  Surface: {surface_water/10:.1f}L", (hud_x + 10, y_offset), color=(180, 180, 180))
    y_offset += LINE_HEIGHT
    
    subsurface = tile.water.total_subsurface_water()
    if subsurface > 0:
        draw_text(screen, font, f"  Ground: {subsurface/10:.1f}L", (hud_x + 10, y_offset), color=(180, 180, 180))
        y_offset += LINE_HEIGHT
    
    if tile.well_output > 0:
        draw_text(screen, font, f"Well: {tile.well_output/10:.2f}L/tick", (hud_x, y_offset), color=(100, 180, 255))
        y_offset += LINE_HEIGHT
    
    if tile.trench:
        draw_text(screen, font, "Trench: Yes", (hud_x, y_offset), color=(180, 180, 120))
        y_offset += LINE_HEIGHT
    
    if structure:
        draw_text(screen, font, f"Structure: {structure.kind.capitalize()}", (hud_x, y_offset), color=(120, 200, 120))
        y_offset += LINE_HEIGHT
        
        if structure.kind == "cistern":
            draw_text(screen, font, f"  Stored: {structure.stored/10:.1f}L", (hud_x + 10, y_offset), color=(180, 180, 180))
            y_offset += LINE_HEIGHT
        elif structure.kind == "planter":
            draw_text(screen, font, f"  Growth: {structure.growth}%", (hud_x + 10, y_offset), color=(180, 180, 180))
            y_offset += LINE_HEIGHT
    
    y_offset += SECTION_SPACING
    
    # Soil profile visualization
    profile_y = y_offset
    draw_soil_profile(screen, font, tile, (hud_x, profile_y), PROFILE_WIDTH, PROFILE_HEIGHT)

    # Night overlay on map area only
    night_alpha = max(0, min(200, int((140 - state.heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface((map_width, map_height), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        screen.blit(overlay, (0, 0))
    
    # Draw log panel at bottom (full width)
    log_panel_y = map_height
    log_panel_height = screen.get_height() - map_height
    
    # Draw separator line
    pygame.draw.line(screen, (80, 80, 80), (0, log_panel_y), (screen.get_width(), log_panel_y), 2)
    
    # Log header
    log_x = 12
    log_y = log_panel_y + 8
    draw_text(screen, font, "EVENT LOG", (log_x, log_y), color=(200, 180, 120))
    log_y += LINE_HEIGHT + 4
    
    # Display recent messages
    available_width = screen.get_width() - 24
    max_messages = (log_panel_height - 40) // 18
    
    for msg in state.messages[-max_messages:]:
        draw_text(screen, font, f"• {msg}", (log_x, log_y), color=(160, 200, 160))
        log_y += 18


def issue(state: GameState, cmd: str, args: List[str]) -> None:
    """
    Issue a command to the game state and run simulation tick if appropriate.
    
    Posts QUIT event if the command returns True.
    """
    quit_now = handle_command(state, cmd, args)
    if quit_now:
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        return
    if cmd not in ("status", "help"):
        simulate_tick(state)


def update_player_position(state: GameState, player_px: List[float], vel: Tuple[float, float], dt: float, tile_size: int) -> None:
    """
    Move player smoothly with collision detection.
    
    Blocks movement into rocks and out of bounds.
    Updates state.player tile coordinates when player crosses tile boundaries.
    """
    if vel == (0.0, 0.0):
        return
    
    vx, vy = vel
    
    # Normalize diagonal movement to prevent faster speed
    if vx != 0.0 and vy != 0.0:
        vx *= DIAGONAL_FACTOR
        vy *= DIAGONAL_FACTOR
    
    new_x = player_px[0] + vx * dt
    new_y = player_px[1] + vy * dt
    
    # Clamp to map bounds
    max_x = state.width * tile_size - 1
    max_y = state.height * tile_size - 1
    new_x = clamp(new_x, 0, max_x)
    new_y = clamp(new_y, 0, max_y)
    
    # Check target tile for collision
    target_tile_x = int(new_x // tile_size)
    target_tile_y = int(new_y // tile_size)
    
    # Block movement into rocks
    if state.tiles[target_tile_x][target_tile_y].kind == "rock":
        # Only block if we're actually moving INTO the rock tile
        current_tile_x = int(player_px[0] // tile_size)
        current_tile_y = int(player_px[1] // tile_size)
        
        if target_tile_x != current_tile_x or target_tile_y != current_tile_y:
            # Trying to enter rock - show message and cancel movement
            if (target_tile_x, target_tile_y) != getattr(state, '_last_rock_blocked', None):
                state.messages.append("Rock blocks the way.")
                state._last_rock_blocked = (target_tile_x, target_tile_y)
            return
    
    # Apply movement
    player_px[0], player_px[1] = new_x, new_y
    state.player = (target_tile_x, target_tile_y)


def run(window_size: MapSize = (20, 15), tile_size: int = TILE_SIZE) -> None:
    """
    Main pygame event loop.
    
    Handles input, updates game state, and renders to screen.
    """
    pygame.init()
    map_w, map_h = window_size
    # Window sized to fit map + log area below + wider sidebar
    log_height = 150
    window_width = map_w * tile_size + SIDEBAR_WIDTH
    window_height = map_h * tile_size + log_height
    screen = pygame.display.set_mode((window_width, window_height))
    pygame.display.set_caption("Kemet Prototype - Desert Terraforming")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Welcome to Kemet. Press H for help.")
    player_px = [state.player[0] * tile_size + tile_size / 2, state.player[1] * tile_size + tile_size / 2]
    tick_timer = 0.0

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_t:
                    issue(state, "dig", [])
                elif event.key == pygame.K_z:
                    issue(state, "lower", [])
                elif event.key == pygame.K_x:
                    issue(state, "raise", [])
                elif event.key == pygame.K_c:
                    issue(state, "build", ["cistern"])
                elif event.key == pygame.K_n:
                    issue(state, "build", ["condenser"])
                elif event.key == pygame.K_p:
                    issue(state, "build", ["planter"])
                elif event.key == pygame.K_e:
                    issue(state, "collect", [])
                elif event.key == pygame.K_f:
                    issue(state, "pour", ["1"])
                elif event.key == pygame.K_v:
                    issue(state, "survey", [])
                elif event.key == pygame.K_SPACE:
                    issue(state, "end", [])
                elif event.key == pygame.K_h:
                    for control in CONTROLS:
                        state.messages.append(control)
        
        # Continuous movement with WASD
        keys = pygame.key.get_pressed()
        vx = vy = 0.0
        if keys[pygame.K_w]:
            vy -= MOVE_SPEED
        if keys[pygame.K_s]:
            vy += MOVE_SPEED
        if keys[pygame.K_a]:
            vx -= MOVE_SPEED
        if keys[pygame.K_d]:
            vx += MOVE_SPEED
        
        update_player_position(state, player_px, (vx, vy), dt, tile_size)
        
        # Automatic simulation ticks
        tick_timer += dt
        while tick_timer >= TICK_INTERVAL:
            simulate_tick(state)
            tick_timer -= TICK_INTERVAL
        
        render(screen, font, state, tile_size, SIDEBAR_WIDTH, tuple(player_px))
        pygame.display.flip()
    
    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
