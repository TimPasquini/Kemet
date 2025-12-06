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
    clamp,
    GameState,
    build_initial_state,
    handle_command,
    simulate_tick,
)

# Game constants
SIDEBAR_WIDTH = 260
TILE_SIZE = 32
MOVE_SPEED = 220  # pixels per second
TICK_INTERVAL = 0.7  # seconds per simulation tick
PLAYER_RADIUS_DIVISOR = 3
STRUCTURE_INSET = 8
TRENCH_INSET = 10
WELL_RADIUS = 6
LINE_HEIGHT = 20
FONT_SIZE = 20

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
    surface.blit(font.render(text, True, color), pos)


def wrap_text(font, text: str, max_width: int) -> List[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split(' ')
    lines = []
    current_line = ""
    
    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        text_surface = font.render(test_line, True, (255, 255, 255))
        if text_surface.get_width() <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines if lines else [text]


def render(screen, font, state: GameState, tile_size: int, sidebar: int, player_px: Tuple[float, float]) -> None:
    screen.fill((20, 20, 25))
    
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
            if hasattr(tile, 'well_output') and tile.well_output > 0:
                # Different colors for seep vs spring
                well_color = (100, 180, 240) if tile.well_output > 0.3 else (70, 140, 220)
                pygame.draw.circle(screen, well_color, rect.center, WELL_RADIUS)
            if hasattr(tile, 'depot') and tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))
    
    # Draw player (use sub-tile pixel position for smooth movement)
    px, py = player_px
    pygame.draw.circle(screen, (240, 240, 90), (int(px), int(py)), tile_size // PLAYER_RADIUS_DIVISOR)
    
    # Sidebar HUD
    hud_x = state.width * tile_size + 12
    sidebar_width = SIDEBAR_WIDTH - 20  # Leave margin for wrapping
    y_offset = 12
    
    draw_text(screen, font, f"Day {state.day}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    draw_text(screen, font, f"Heat {state.heat:.2f}", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    phase = "Night" if state.heat < 1.0 else "Day"
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
    
    if hasattr(tile, 'well_output') and tile.well_output > 0:
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
    
    # Messages with wrapping
    y_offset += 6  # Small gap before log
    draw_text(screen, font, "Log:", (hud_x, y_offset))
    y_offset += LINE_HEIGHT
    
    # Word wrap messages to fit in sidebar
    for msg in state.messages[-12:]:
        wrapped_lines = wrap_text(font, f"- {msg}", sidebar_width)
        for line in wrapped_lines:
            draw_text(screen, font, line, (hud_x, y_offset), color=(160, 200, 160))
            y_offset += 18

    # Night overlay
    night_alpha = max(0, min(200, int((1.4 - state.heat) * 180)))
    if night_alpha > 0:
        overlay = pygame.Surface((state.width * tile_size, state.height * tile_size), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        screen.blit(overlay, (0, 0))


def issue(state: GameState, cmd: str, args: List[str]) -> None:
    quit_now = handle_command(state, cmd, args)
    if quit_now:
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        return
    if cmd not in ("status", "help"):
        simulate_tick(state)


def update_player_position(state: GameState, player_px: List[float], vel: Tuple[float, float], dt: float, tile_size: int) -> None:
    """Move player smoothly; block rocks and bounds, update state.player tile coords."""
    if vel == (0.0, 0.0):
        return
    
    vx, vy = vel
    
    # Normalize diagonal movement to prevent faster speed
    if vx != 0.0 and vy != 0.0:
        magnitude = (vx**2 + vy**2)**0.5
        vx = vx / magnitude * MOVE_SPEED
        vy = vy / magnitude * MOVE_SPEED
    
    new_x = player_px[0] + vx * dt
    new_y = player_px[1] + vy * dt
    max_x = state.width * tile_size - 1
    max_y = state.height * tile_size - 1
    new_x = clamp(new_x, 0, max_x)
    new_y = clamp(new_y, 0, max_y)
    target = (int(new_x // tile_size), int(new_y // tile_size))
    if state.tiles[target[0]][target[1]].kind == "rock":
        return  # simple block
    player_px[0], player_px[1] = new_x, new_y
    state.player = target


def run(window_size: MapSize = (20, 15), tile_size: int = TILE_SIZE) -> None:
    pygame.init()
    map_w, map_h = window_size
    # Calculate required height for sidebar content
    min_sidebar_height = 600  # Ensure enough space for all HUD elements
    window_height = max(map_h * tile_size, min_sidebar_height)
    screen = pygame.display.set_mode((map_w * tile_size + SIDEBAR_WIDTH, window_height))
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
