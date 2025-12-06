"""
Pygame-CE frontend for the Kemet prototype.
Controls (while window focused):
- W/A/S/D: move
- T: dig trench
- C: build cistern
- N: build condenser
- P: build planter
- E: collect water on tile
- F: pour 1 water on tile
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


def render(screen, font, state: GameState, tile_size: int, sidebar: int, player_px: Tuple[float, float]) -> None:
    screen.fill((20, 20, 25))
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            color = color_for_tile(tile, ttype)
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            pygame.draw.rect(screen, color, rect)
            if tile.trench:
                pygame.draw.rect(screen, (80, 80, 60), rect.inflate(-10, -10))
    # Structures
    for (x, y), structure in state.structures.items():
        rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
        pygame.draw.rect(screen, (30, 30, 30), rect.inflate(-8, -8))
        label = {"cistern": "C", "condenser": "N", "planter": "F"}.get(structure.kind, "?")
        draw_text(screen, font, label, (rect.x + 6, rect.y + 4))
    # Wells and depot markers
    for y in range(state.height):
        for x in range(state.width):
            tile = state.tiles[x][y]
            rect = pygame.Rect(x * tile_size, y * tile_size, tile_size - 1, tile_size - 1)
            if tile.well_output > 0:
                pygame.draw.circle(screen, (70, 140, 220), rect.center, 6)
            if tile.depot:
                pygame.draw.rect(screen, (200, 200, 60), rect.inflate(-10, -10), border_radius=3)
                draw_text(screen, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))
    # Player (use sub-tile pixel position for smooth movement)
    px, py = player_px
    pygame.draw.circle(screen, (240, 240, 90), (int(px), int(py)), tile_size // 3)
    # Sidebar HUD
    hud_x = state.width * tile_size + 12
    draw_text(screen, font, f"Day {state.day}", (hud_x, 12))
    draw_text(screen, font, f"Heat {state.heat:.2f}", (hud_x, 32))
    phase = "Night" if state.heat < 1.0 else "Day"
    draw_text(screen, font, f"Cycle: {phase}", (hud_x, 52))
    draw_text(screen, font, f"Dust in {state.dust_timer}", (hud_x, 72))
    rain_txt = "Raining" if state.raining else f"Rain in {state.rain_timer}"
    draw_text(screen, font, rain_txt, (hud_x, 92))
    inv = state.inventory
    draw_text(screen, font, f"Water: {inv['water']:.1f}", (hud_x, 80))
    draw_text(screen, font, f"Scrap: {int(inv['scrap'])}", (hud_x, 100))
    draw_text(screen, font, f"Seeds: {int(inv['seeds'])}", (hud_x, 120))
    draw_text(screen, font, f"Biomass: {int(inv['biomass'])}", (hud_x, 140))
    draw_text(screen, font, "Controls:", (hud_x, 180))
    controls = ["WASD move", "T trench", "Z lower", "X raise", "C cistern", "N condenser", "P planter", "E collect", "F pour 1", "V survey", "Space end day", "Esc quit"]
    for idx, line in enumerate(controls):
        draw_text(screen, font, line, (hud_x, 200 + 18 * idx), color=(180, 180, 180))
    # Messages
    msg_y = 200 + 18 * len(controls) + 12
    draw_text(screen, font, "Log:", (hud_x, msg_y))
    for i, msg in enumerate(state.messages[-12:]):
        draw_text(screen, font, f"- {msg}", (hud_x, msg_y + 18 * (i + 1)), color=(160, 200, 160))

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
    new_x = player_px[0] + vel[0] * dt
    new_y = player_px[1] + vel[1] * dt
    max_x = state.width * tile_size - 1
    max_y = state.height * tile_size - 1
    new_x = clamp(new_x, 0, max_x)
    new_y = clamp(new_y, 0, max_y)
    target = (int(new_x // tile_size), int(new_y // tile_size))
    if state.tiles[target[0]][target[1]].kind == "rock":
        return  # simple block
    player_px[0], player_px[1] = new_x, new_y
    state.player = target


def run(window_size: MapSize = (20, 15), tile_size: int = 32) -> None:
    pygame.init()
    map_w, map_h = window_size
    sidebar = 260
    screen = pygame.display.set_mode((map_w * tile_size + sidebar, map_h * tile_size))
    pygame.display.set_caption("Kemet Prototype (pygame-ce)")
    font = pygame.font.Font(None, 20)
    clock = pygame.time.Clock()
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Pygame mode: press H for controls.")
    player_px = [state.player[0] * tile_size + tile_size / 2, state.player[1] * tile_size + tile_size / 2]
    move_speed = 220  # pixels per second
    tick_timer = 0.0
    tick_interval = 0.7  # seconds per simulation tick

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
                    state.messages.append("Controls: WASD move, T trench, Z lower, X raise, C cistern, N condenser, P planter, E collect, F pour 1, V survey, Space end day, Esc quit")
        keys = pygame.key.get_pressed()
        vx = vy = 0.0
        if keys[pygame.K_w]:
            vy -= move_speed
        if keys[pygame.K_s]:
            vy += move_speed
        if keys[pygame.K_a]:
            vx -= move_speed
        if keys[pygame.K_d]:
            vx += move_speed
        update_player_position(state, player_px, (vx, vy), dt, tile_size)
        tick_timer += dt
        while tick_timer >= tick_interval:
            simulate_tick(state)
            tick_timer -= tick_interval
        render(screen, font, state, tile_size, sidebar, tuple(player_px))
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
