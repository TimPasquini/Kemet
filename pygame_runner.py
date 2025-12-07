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
- F: pour 1 water on tile
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

# Display constants
SIDEBAR_WIDTH = 260
TILE_SIZE = 32
LINE_HEIGHT = 20
FONT_SIZE = 20

# Movement and collision constants
MOVE_SPEED = 220  # pixels per second
DIAGONAL_FACTOR = 0.707  # 1/sqrt(2) for normalized diagonal movement

# Rendering constants
TICK_INTERVAL = 0.7  # seconds per simulation tick
PLAYER_RADIUS_DIVISOR = 3
STRUCTURE_INSET = 8
TRENCH_INSET = 10
WELL_RADIUS = 6

# Control scheme - single source of truth
CONTROLS = [
    "WASD move",
    "T trench",
    "Z lower",
    "X raise",
    "C cistern",
    "N condenser",
    "P planter",
    "E collect",
    "F pour 1",
    "V survey",
    "Space end day",
    "Esc quit"
]

MapSize = Tuple[int, int]


def color_for_tile(state_tile, tile_type) -> Tuple[int, int, int]:
    """
    Determine the display color for a tile based on hydration and terrain type.
    
    Prioritizes water visualization over base terrain color.
    """
    # Hydration overlays
    if state_tile.hydration >= 1.0:
        return (48, 133, 214)  # deep water
    if state_tile.hydration >= 0.5:
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


def wrap_text(font, text: str, max_width: int) -> List[str]:
    """
    Wrap text to fit within max_width pixels.
    
    Uses font.size() instead of rendering for efficiency.
    """
    words = text.split(' ')
    lines = []
    current_line = ""
    
    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        width = font.size(test_line)[0]
        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines if lines else [text]


def render(screen, font, state: GameState, tile_size: int, sidebar: int, player_px: Tuple[float, float]) -> None:
    """
    Render the complete game state to the pygame window.
    
    Draws tiles, structures, player, and HUD sidebar with inventory.
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
                # Different colors for seep vs spring
                well_color = (100, 180, 240) if tile.well_output > 0.3 else (70, 140, 220)
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
    
    draw_text(screen, font, f"Day {state.day}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Heat {state.heat:.2f}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    phase = "Night" if state.heat < HEAT_NIGHT_THRESHOLD else "Day"
    draw_text(screen, font, f"Cycle: {phase}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    rain_txt = "Raining!" if state.raining else f"Rain in {state.rain_timer}"
    draw_text(screen, font, rain_txt, (hud_x, y_offset))
    y_offset += LINE_HEIGHT * 1.5  # Extra space before inventory
    
    inv = state.inventory
    draw_text(screen, font, f"Water: {inv['water']:.1f}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Scrap: {int(inv['scrap'])}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Seeds: {int(inv['seeds'])}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Biomass: {int(inv['biomass'])}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT * 1.5  # Extra space before player tile info
    
    # Current tile info
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))
    
    draw_text(screen, font, f"Position: {x},{y}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Terrain: {tile.kind}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Elevation: {tile.elevation:.2f}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Water: {tile.hydration:.2f}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    if tile.well_output > 0:
        draw_text(screen, font, f"Well: {tile.well_output:.2f}/t", (hud_x, y_offset))
        y_offset += LINE_HEIGHT
    
    if tile.trench:
        draw_text(screen, font, "Trench: Yes", (hud_x, y_offset))
        y_offset += LINE_HEIGHT
    
    if structure:
        draw_text(screen, font, f"Structure: {structure.kind}", (hud_x, y_offset))
        y_offset += LINE_HEIGHT
        if structure.kind == "cistern":
            draw_text(screen, font, f"Stored: {structure.stored:.2f}", (hud_x, y_offset))
            y_offset += LINE_HEIGHT
        elif structure.kind == "planter":
            draw_text(screen, font, f"Growth: {structure.growth:.2f}", (hud_x, y_offset))
            y_offset += LINE_HEIGHT
    
    y_offset += LINE_HEIGHT * 0.5  # Extra space before controls
    
    draw_text(screen, font, "Controls:", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    for line in CONTROLS:
        draw_text(screen, font, line, (hud_x, y_offset), color=(180, 180, 180))
        y_offset += 18  # Slightly tighter spacing for controls

    # Night overlay on map area only
    night_alpha = max(0, min(200, int((1.4 - state.heat) * 180)))
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
    draw_text(screen, font, "Event Log:", (log_x, log_y), color=(200, 200, 200))
    log_y += LINE_HEIGHT + 4
    
    # Display recent messages (no wrapping needed with full width)
    available_width = screen.get_width() - 24  # margin on both sides
    max_messages = (log_panel_height - 40) // 18  # how many fit
    
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
    # Window sized to fit map + log area below
    log_height = 150  # Height of bottom log panel
    window_width = map_w * tile_size + SIDEBAR_WIDTH
    window_height = map_h * tile_size + log_height
    screen = pygame.display.set_mode((window_width, window_height))
    pygame.display.set_caption("Kemet Prototype (pygame-ce)")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Pygame mode: press H for controls.")
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
                    state.messages.append("Controls: " + ", ".join(CONTROLS))
        
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
