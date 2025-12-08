"""
Pygame-CE frontend for the Kemet prototype.

Controls:
- W/A/S/D: move
- 1-9: select and use tool
- Space: rest (at night)
- H: show help
- ESC: quit
"""
from __future__ import annotations

import sys
from typing import Dict, List, Tuple, Optional

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
from tools import TOOLS, get_tool_by_number, Tool
from keybindings import CONTROL_DESCRIPTIONS, MOVE_KEYS, TOOL_KEYS, HELP_KEY, QUIT_KEY

# Type alias
Color = Tuple[int, int, int]

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
TICK_INTERVAL = 25.0  # seconds per simulation tick (25s × 12 ticks = 5 min day)
PLAYER_RADIUS_DIVISOR = 3
STRUCTURE_INSET = 8
TRENCH_INSET = 10
WELLSPRING_RADIUS = 6

# Profile meter constants
PROFILE_WIDTH = 140
PROFILE_HEIGHT = 240
PROFILE_MARGIN = 10

# Toolbar constants
TOOLBAR_HEIGHT = 32
TOOLBAR_BG_COLOR = (30, 30, 35)
TOOLBAR_SELECTED_COLOR = (60, 55, 40)
TOOLBAR_TEXT_COLOR = (200, 200, 180)

MapSize = Tuple[int, int]

# Biome base colors
BIOME_COLORS: Dict[str, Color] = {
    "dune": (204, 174, 120),
    "flat": (188, 158, 112),
    "wadi": (150, 125, 96),
    "rock": (128, 128, 128),
    "salt": (220, 220, 210),
}

# Elevation shading constants
ELEVATION_BRIGHTNESS_MIN = 0.7   # Darkest (lowest elevation)
ELEVATION_BRIGHTNESS_MAX = 1.3   # Brightest (highest elevation)

# Material blend weight
MATERIAL_BLEND_WEIGHT = 0.35
ORGANICS_BLEND_WEIGHT = 0.50


def calculate_elevation_range(state: "GameState") -> Tuple[float, float]:
    """Get min/max elevation across all tiles for shading normalization."""
    elevations = [
        state.tiles[x][y].elevation
        for x in range(state.width)
        for y in range(state.height)
    ]
    return (min(elevations), max(elevations))


def elevation_brightness(elevation: float, min_elev: float, max_elev: float) -> float:
    """Return brightness multiplier based on elevation within map range."""
    if max_elev == min_elev:
        return 1.0
    normalized = (elevation - min_elev) / (max_elev - min_elev)
    return ELEVATION_BRIGHTNESS_MIN + (normalized * (ELEVATION_BRIGHTNESS_MAX - ELEVATION_BRIGHTNESS_MIN))


def apply_brightness(color: Color, brightness: float) -> Color:
    """Apply brightness multiplier to a color, clamping to valid range."""
    return tuple(max(0, min(255, int(c * brightness))) for c in color)


def blend_colors(color1: Color, color2: Color, weight: float = 0.5) -> Color:
    """Blend two RGB colors. Weight is amount of color2 (0.0-1.0)."""
    return tuple(int(c1 * (1 - weight) + c2 * weight) for c1, c2 in zip(color1, color2))


def get_surface_material_color(tile) -> Color | None:
    """Get color from topmost soil layer material."""
    terrain = tile.terrain

    # Check organics first (player-built layer)
    if terrain.organics_depth > 0:
        props = MATERIAL_LIBRARY.get("humus")
        if props:
            return props.display_color

    # Then topsoil material
    material = terrain.topsoil_material
    props = MATERIAL_LIBRARY.get(material)
    if props:
        return props.display_color

    return None


def color_for_tile(state_tile, tile_type, elevation_range: Tuple[float, float] = None) -> Color:
    """
    Determine the display color for a tile based on terrain, materials, and elevation.

    Color is computed by:
    1. Start with biome base color
    2. Blend in surface material color (organics or topsoil)
    3. Apply elevation-based brightness shading
    4. Override with water color if sufficiently wet
    """
    # Water overlay takes priority for wet tiles
    if state_tile.hydration >= 10.0:
        return (48, 133, 214)  # deep water
    if state_tile.hydration >= 5.0:
        return (92, 180, 238)  # damp

    # Start with biome base color
    base_color = BIOME_COLORS.get(tile_type.name, (200, 200, 200))

    # Blend in surface material color
    material_color = get_surface_material_color(state_tile)
    if material_color:
        # Use stronger blend for organics (player progress visible)
        weight = ORGANICS_BLEND_WEIGHT if state_tile.terrain.organics_depth > 0 else MATERIAL_BLEND_WEIGHT
        base_color = blend_colors(base_color, material_color, weight)

    # Apply elevation shading if range provided
    if elevation_range:
        min_elev, max_elev = elevation_range
        brightness = elevation_brightness(state_tile.elevation, min_elev, max_elev)
        base_color = apply_brightness(base_color, brightness)

    return base_color


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


def draw_toolbar(
    surface, font, tools: List[Tool], selected_idx: int,
    pos: Tuple[int, int], width: int, height: int
) -> None:
    """Draw numbered toolbar with tool icons and names."""
    x, y = pos
    tool_count = len(tools)
    tool_width = width // tool_count

    # Background
    pygame.draw.rect(surface, TOOLBAR_BG_COLOR, (x, y, width, height))
    pygame.draw.line(surface, (60, 60, 60), (x, y), (x + width, y), 1)

    for i, tool in enumerate(tools):
        tx = x + (i * tool_width)

        # Highlight selected tool
        if i == selected_idx:
            pygame.draw.rect(
                surface, TOOLBAR_SELECTED_COLOR,
                (tx + 1, y + 1, tool_width - 2, height - 2)
            )

        # Draw number and icon
        num_text = f"{i + 1}"
        draw_text(surface, font, num_text, (tx + 4, y + 2), color=(150, 150, 130))
        draw_text(surface, font, tool.icon, (tx + 18, y + 2), color=TOOLBAR_TEXT_COLOR)

        # Draw tool name (abbreviated if needed)
        name = tool.name[:6]
        draw_text(surface, font, name, (tx + 4, y + 16), color=(140, 140, 140))

        # Separator
        if i < tool_count - 1:
            pygame.draw.line(
                surface, (50, 50, 50),
                (tx + tool_width - 1, y + 4),
                (tx + tool_width - 1, y + height - 4), 1
            )


def draw_help_overlay(
    surface, font, controls: List[str],
    pos: Tuple[int, int], available_width: int, available_height: int
) -> None:
    """Draw controls in a multi-column grid layout."""
    x, y = pos
    col_width = 130  # Width per control entry
    cols = max(1, available_width // col_width)
    row_height = 18

    # Draw background
    pygame.draw.rect(
        surface, (25, 25, 30),
        (x - 4, y - 4, available_width, available_height), 0
    )

    draw_text(surface, font, "CONTROLS", (x, y), color=(220, 200, 120))
    y += row_height + 4

    for i, control in enumerate(controls):
        col = i % cols
        row = i // cols
        cx = x + (col * col_width)
        cy = y + (row * row_height)

        if cy + row_height < pos[1] + available_height:
            draw_text(surface, font, control, (cx, cy), color=(180, 180, 160))


def render(
    screen, font, state: GameState, tile_size: int, sidebar: int,
    player_px: Tuple[float, float], selected_tool: int = 0, show_help: bool = False
) -> None:
    """
    Render the complete game state to the pygame window.

    Draws tiles, structures, player, HUD sidebar with inventory and soil profile.
    Log messages displayed in bottom panel across full width.
    """
    screen.fill((20, 20, 25))

    map_width = state.width * tile_size
    map_height = state.height * tile_size

    # Calculate elevation range for shading (cache could be added for performance)
    elevation_range = calculate_elevation_range(state)

    # Draw tiles
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            color = color_for_tile(tile, ttype, elevation_range)
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
    
    # Draw wellsprings and depot markers
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            if tile.wellspring_output > 0:
                # Different colors for seep vs spring (converting units to L for comparison)
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(screen, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))
    
    # Draw player (use sub-tile pixel position for smooth movement)
    px, py = player_px
    pygame.draw.circle(screen, (240, 240, 90), (int(px), int(py)), tile_size // PLAYER_RADIUS_DIVISOR)
    
    # Sidebar HUD (left of soil profile)
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
    
    # -- note: inventory moved to bottom-right panel; omit inventory here --
    
    # Current tile section (remains left of soil profile)
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
    
    if tile.wellspring_output > 0:
        draw_text(screen, font, f"Wellspring: {tile.wellspring_output/10:.2f}L/tick", (hud_x, y_offset), color=(100, 180, 255))
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
    
    # Position soil profile in the upper-right area (thinner, per request)
    soil_x = screen.get_width() - PROFILE_WIDTH - PROFILE_MARGIN
    soil_y = 12
    draw_soil_profile(screen, font, tile, (soil_x, soil_y), PROFILE_WIDTH, PROFILE_HEIGHT)
    
    # Inventory panel anchored bottom-right (square)
    inv_w = 180
    inv_h = 140
    inv_x = screen.get_width() - inv_w - 12
    inv_y = map_height - inv_h - 12
    # Ensure inventory doesn't go above the map area (clamp)
    if inv_y < 12:
        inv_y = 12
    pygame.draw.rect(screen, (40, 40, 40), (inv_x, inv_y, inv_w, inv_h), 2)
    ix = inv_x + 8
    iy = inv_y + 8
    draw_text(screen, font, "Inventory", (ix, iy))
    iy += LINE_HEIGHT
    inv = state.inventory
    draw_text(screen, font, f"Water: {inv['water']/10:.1f}L", (ix, iy)); iy += LINE_HEIGHT
    draw_text(screen, font, f"Scrap: {int(inv['scrap'])}", (ix, iy)); iy += LINE_HEIGHT
    draw_text(screen, font, f"Seeds: {int(inv['seeds'])}", (ix, iy)); iy += LINE_HEIGHT
    draw_text(screen, font, f"Biomass: {int(inv['biomass'])}kg", (ix, iy))
    
    # Night overlay on map area only
    night_alpha = max(0, min(200, int((140 - state.heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface((map_width, map_height), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        screen.blit(overlay, (0, 0))

    # Draw toolbar at bottom of map area
    toolbar_y = map_height
    draw_toolbar(screen, font, TOOLS, selected_tool, (0, toolbar_y), map_width, TOOLBAR_HEIGHT)

    # Draw log panel below toolbar (full width)
    log_panel_y = map_height + TOOLBAR_HEIGHT
    log_panel_height = screen.get_height() - log_panel_y

    # Draw separator line
    pygame.draw.line(screen, (80, 80, 80), (0, log_panel_y), (screen.get_width(), log_panel_y), 2)

    log_x = 12
    log_y = log_panel_y + 8

    if show_help:
        # Show help overlay instead of log
        draw_help_overlay(
            screen, font, CONTROL_DESCRIPTIONS,
            (log_x, log_y), screen.get_width() - 24, log_panel_height - 16
        )
    else:
        # Log header
        draw_text(screen, font, "EVENT LOG", (log_x, log_y), color=(200, 180, 120))
        log_y += LINE_HEIGHT + 4

        # Display recent messages
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

    # Window sized to fit map + toolbar + log area below + sidebar
    log_height = 120
    window_width = map_w * tile_size + SIDEBAR_WIDTH
    window_height = map_h * tile_size + TOOLBAR_HEIGHT + log_height

    screen = pygame.display.set_mode((window_width, window_height))
    pygame.display.set_caption("Kemet - Desert Terraforming")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Welcome to Kemet. Press H for help, 1-9 to select tools.")

    player_px = [
        state.player[0] * tile_size + tile_size / 2,
        state.player[1] * tile_size + tile_size / 2
    ]
    tick_timer = 0.0

    # UI state
    selected_tool = 0  # Currently selected tool index
    show_help = False  # Toggle help overlay

    running = True
    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                # System keys
                if event.key == pygame.K_ESCAPE:
                    running = False

                # Help toggle
                elif event.key == pygame.K_h:
                    show_help = not show_help

                # Rest/end day
                elif event.key == pygame.K_SPACE:
                    issue(state, "end", [])

                # Number keys select AND use tool
                elif event.key in TOOL_KEYS:
                    tool_num = TOOL_KEYS[event.key]
                    tool = get_tool_by_number(tool_num)
                    if tool:
                        selected_tool = tool_num - 1
                        issue(state, tool.action, tool.args)

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

        render(
            screen, font, state, tile_size, SIDEBAR_WIDTH,
            tuple(player_px), selected_tool, show_help
        )
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)

