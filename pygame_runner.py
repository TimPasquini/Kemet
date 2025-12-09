# pygame_runner.py
"""
Pygame-CE frontend for the Kemet prototype.

Architecture:
- World space: tile/pixel coordinates in the game world (can be larger than screen)
- Virtual screen space: fixed 1280x720 UI layout surface
- Screen space: actual window pixels (scales with resize)

The camera controls which portion of the world is visible in the map viewport.
All UI elements render at virtual screen coordinates.
Mouse input transforms: screen -> virtual -> world (for map clicks)

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
from dataclasses import dataclass
from typing import List, Tuple, Optional

try:
    import pygame
except ImportError as exc:
    raise SystemExit("pygame-ce is required. Install with: pip install pygame-ce") from exc

from main import (
    GameState,
    build_initial_state,
    handle_command,
    simulate_tick,
    end_day,
)
from camera import Camera
from tools import get_toolbar, Toolbar
from ui_state import get_ui_state, UIState
from keybindings import (
    CONTROL_DESCRIPTIONS,
    TOOL_KEYS,
    USE_TOOL_KEY,
    INTERACT_KEY,
    TOOL_MENU_KEY,
    REST_KEY,
    HELP_KEY,
)
from utils import clamp
from config import (
    TILE_SIZE,
    MOVE_SPEED,
    DIAGONAL_FACTOR,
    TICK_INTERVAL,
    PROFILE_WIDTH,
    PROFILE_HEIGHT,
    PROFILE_MARGIN,
    TOOLBAR_HEIGHT,
    MAP_SIZE,
    FONT_SIZE,
)
from render import (
    calculate_elevation_range,
    render_hud,
    render_inventory,
    render_soil_profile,
    render_toolbar,
    render_help_overlay,
    render_event_log,
)

# Virtual screen dimensions (fixed internal resolution)
VIRTUAL_WIDTH = 1280
VIRTUAL_HEIGHT = 720

# Layout constants for virtual screen
SIDEBAR_WIDTH = 280
MAP_VIEWPORT_WIDTH = VIRTUAL_WIDTH - SIDEBAR_WIDTH  # 1000
MAP_VIEWPORT_HEIGHT = VIRTUAL_HEIGHT - TOOLBAR_HEIGHT - 100  # 588
LOG_PANEL_HEIGHT = 100


@dataclass
class VirtualLayout:
    """Fixed layout regions in virtual screen coordinates."""
    # Map viewport (where the world is displayed)
    map_rect: pygame.Rect

    # Sidebar (HUD, soil profile, inventory)
    sidebar_rect: pygame.Rect

    # Bottom panels
    toolbar_rect: pygame.Rect
    log_panel_rect: pygame.Rect

    @classmethod
    def create(cls) -> VirtualLayout:
        """Create the standard layout for virtual screen."""
        map_rect = pygame.Rect(0, 0, MAP_VIEWPORT_WIDTH, MAP_VIEWPORT_HEIGHT)
        sidebar_rect = pygame.Rect(MAP_VIEWPORT_WIDTH, 0, SIDEBAR_WIDTH, VIRTUAL_HEIGHT)
        toolbar_rect = pygame.Rect(0, MAP_VIEWPORT_HEIGHT, MAP_VIEWPORT_WIDTH, TOOLBAR_HEIGHT)
        log_panel_rect = pygame.Rect(0, MAP_VIEWPORT_HEIGHT + TOOLBAR_HEIGHT, VIRTUAL_WIDTH, LOG_PANEL_HEIGHT)

        return cls(map_rect, sidebar_rect, toolbar_rect, log_panel_rect)


def screen_to_virtual(
    screen_pos: Tuple[int, int],
    screen_size: Tuple[int, int],
) -> Tuple[int, int]:
    """Transform screen coordinates to virtual screen coordinates."""
    screen_w, screen_h = screen_size
    scale = min(screen_w / VIRTUAL_WIDTH, screen_h / VIRTUAL_HEIGHT)
    scaled_w = VIRTUAL_WIDTH * scale
    scaled_h = VIRTUAL_HEIGHT * scale
    offset_x = (screen_w - scaled_w) / 2
    offset_y = (screen_h - scaled_h) / 2

    vx = int((screen_pos[0] - offset_x) / scale)
    vy = int((screen_pos[1] - offset_y) / scale)

    return (vx, vy)


def virtual_to_world(
    virtual_pos: Tuple[int, int],
    layout: VirtualLayout,
    camera: Camera,
) -> Optional[Tuple[float, float]]:
    """
    Transform virtual screen coordinates to world coordinates.
    Returns None if position is outside the map viewport.
    """
    if not layout.map_rect.collidepoint(virtual_pos):
        return None

    # Position within the map viewport
    vp_x = virtual_pos[0] - layout.map_rect.x
    vp_y = virtual_pos[1] - layout.map_rect.y

    # Scale from viewport to camera viewport size
    scale_x = camera.viewport_width / layout.map_rect.width
    scale_y = camera.viewport_height / layout.map_rect.height

    cam_vp_x = vp_x * scale_x
    cam_vp_y = vp_y * scale_y

    # Convert to world coordinates
    world_x, world_y = camera.viewport_to_world(cam_vp_x, cam_vp_y)

    return (world_x, world_y)


def render_map_viewport(
    surface: pygame.Surface,
    font,
    state: GameState,
    camera: Camera,
    tile_size: int,
    elevation_range: Tuple[float, float],
    player_world_pos: Tuple[float, float],
) -> None:
    """Render the visible portion of the world to the map viewport surface."""
    surface.fill((20, 20, 25))

    # Get visible tile range
    start_x, start_y, end_x, end_y = camera.get_visible_tile_range()

    # Import here to avoid circular dependency
    from mapgen import TILE_TYPES
    from render.colors import color_for_tile
    from render.primitives import draw_text
    from config import STRUCTURE_INSET, TRENCH_INSET, WELLSPRING_RADIUS, PLAYER_RADIUS_DIVISOR

    # Draw visible tiles
    for ty in range(start_y, end_y):
        for tx in range(start_x, end_x):
            tile = state.tiles[tx][ty]
            color = color_for_tile(tile, TILE_TYPES[tile.kind], elevation_range)

            # Convert tile position to viewport position
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)

            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)
            pygame.draw.rect(surface, color, rect)

            if tile.trench:
                pygame.draw.rect(surface, (80, 80, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET))

    # Draw structures
    for (sx, sy), structure in state.structures.items():
        if not camera.is_tile_visible(sx, sy):
            continue
        world_x, world_y = camera.tile_to_world(sx, sy)
        vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
        rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)
        pygame.draw.rect(surface, (30, 30, 30), rect.inflate(-STRUCTURE_INSET, -STRUCTURE_INSET))
        draw_text(surface, font, structure.kind[0].upper(), (rect.x + 6, rect.y + 4))

    # Draw special features (wellsprings, depots)
    for ty in range(start_y, end_y):
        for tx in range(start_x, end_x):
            tile = state.tiles[tx][ty]
            world_x, world_y = camera.tile_to_world(tx, ty)
            vp_x, vp_y = camera.world_to_viewport(world_x, world_y)
            rect = pygame.Rect(int(vp_x), int(vp_y), tile_size - 1, tile_size - 1)

            if tile.wellspring_output > 0:
                spring_color = (100, 180, 240) if tile.wellspring_output / 10 > 0.5 else (70, 140, 220)
                pygame.draw.circle(surface, spring_color, rect.center, WELLSPRING_RADIUS)
            if tile.depot:
                pygame.draw.rect(surface, (200, 200, 60), rect.inflate(-TRENCH_INSET, -TRENCH_INSET), border_radius=3)
                draw_text(surface, font, "D", (rect.x + 6, rect.y + 4), color=(40, 40, 20))

    # Draw player
    player_vp_x, player_vp_y = camera.world_to_viewport(player_world_pos[0], player_world_pos[1])
    player_vp_x, player_vp_y = int(player_vp_x), int(player_vp_y)

    pygame.draw.circle(
        surface,
        (240, 240, 90),
        (player_vp_x, player_vp_y),
        tile_size // PLAYER_RADIUS_DIVISOR,
    )

    # Draw action timer bar if busy
    if state.is_busy():
        bar_width = tile_size
        bar_height = 4
        bar_x = player_vp_x - bar_width // 2
        bar_y = player_vp_y - tile_size // 2 - bar_height - 2
        progress = state.get_action_progress()
        pygame.draw.rect(surface, (50, 50, 50), (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(surface, (200, 200, 80), (bar_x, bar_y, int(bar_width * progress), bar_height))

    # Draw night overlay
    night_alpha = max(0, min(200, int((140 - state.heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        surface.blit(overlay, (0, 0))


def render_to_virtual_screen(
    virtual_screen: pygame.Surface,
    font,
    state: GameState,
    camera: Camera,
    tile_size: int,
    elevation_range: Tuple[float, float],
    player_world_pos: Tuple[float, float],
    toolbar: Toolbar,
    ui_state: UIState,
    layout: VirtualLayout,
    show_help: bool,
) -> None:
    """Render everything to the virtual screen at fixed resolution."""
    virtual_screen.fill((20, 20, 25))

    # 1. Render map viewport
    map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))
    render_map_viewport(map_surface, font, state, camera, tile_size, elevation_range, player_world_pos)

    # Scale map surface to fit the layout's map rect
    scaled_map = pygame.transform.scale(map_surface, layout.map_rect.size)
    virtual_screen.blit(scaled_map, layout.map_rect.topleft)

    # 2. Render sidebar elements
    sidebar_x = layout.sidebar_rect.x + 12
    y_offset = 12

    # HUD
    render_hud(virtual_screen, font, state, sidebar_x, y_offset)

    # Soil profile
    soil_x = layout.sidebar_rect.x + PROFILE_MARGIN
    soil_y = 180  # Below HUD
    px, py = state.player
    render_soil_profile(virtual_screen, font, state.tiles[px][py], (soil_x, soil_y), PROFILE_WIDTH, PROFILE_HEIGHT - 22)

    # Inventory
    inv_w, inv_h = 180, 140
    inv_x = VIRTUAL_WIDTH - inv_w - 12
    inv_y = layout.map_rect.bottom - inv_h - 12
    render_inventory(virtual_screen, font, state, (inv_x, inv_y), inv_w, inv_h)

    # 3. Render toolbar
    render_toolbar(virtual_screen, font, toolbar, layout.toolbar_rect.topleft,
                   layout.toolbar_rect.width, TOOLBAR_HEIGHT, ui_state)

    # Update ui_state bounds (in virtual coordinates)
    ui_state.toolbar_rect = layout.toolbar_rect
    ui_state.tool_slot_width = layout.toolbar_rect.width // len(toolbar.tools) if toolbar.tools else 0
    ui_state.log_panel_rect = layout.log_panel_rect

    # 4. Render log panel
    pygame.draw.line(virtual_screen, (80, 80, 80),
                     (0, layout.log_panel_rect.y),
                     (VIRTUAL_WIDTH, layout.log_panel_rect.y), 2)

    log_x, log_y = 12, layout.log_panel_rect.y + 8
    if show_help:
        render_help_overlay(virtual_screen, font, CONTROL_DESCRIPTIONS,
                            (log_x, log_y), VIRTUAL_WIDTH - 24, LOG_PANEL_HEIGHT - 16)
    else:
        render_event_log(virtual_screen, font, state,
                         (log_x, log_y), LOG_PANEL_HEIGHT, ui_state.log_scroll_offset)


def blit_virtual_to_screen(virtual_screen: pygame.Surface, screen: pygame.Surface) -> None:
    """Scale and blit the virtual screen to the actual display, with letterboxing."""
    screen_w, screen_h = screen.get_size()
    scale = min(screen_w / VIRTUAL_WIDTH, screen_h / VIRTUAL_HEIGHT)
    scaled_w = int(VIRTUAL_WIDTH * scale)
    scaled_h = int(VIRTUAL_HEIGHT * scale)
    offset_x = (screen_w - scaled_w) // 2
    offset_y = (screen_h - scaled_h) // 2

    # Fill letterbox areas
    screen.fill((0, 0, 0))

    # Scale and blit
    scaled = pygame.transform.scale(virtual_screen, (scaled_w, scaled_h))
    screen.blit(scaled, (offset_x, offset_y))


def issue(state: GameState, cmd: str, args: List[str]) -> None:
    """Issues a command and sets the player's action timer."""
    if state.is_busy():
        return

    if cmd == "end":
        end_day(state)
        return

    if handle_command(state, cmd, args):
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        return

    state.start_action(cmd)


def update_player_position(
    state: GameState,
    player_world_pos: List[float],
    vel: Tuple[float, float],
    dt: float,
    tile_size: int,
) -> None:
    """Update player world position and tile position based on velocity."""
    if state.is_busy():
        return

    if vel == (0.0, 0.0):
        return

    vx, vy = vel
    if vx != 0.0 and vy != 0.0:
        vx *= DIAGONAL_FACTOR
        vy *= DIAGONAL_FACTOR

    world_width = state.width * tile_size
    world_height = state.height * tile_size

    new_x = clamp(player_world_pos[0] + vx * dt, 0, world_width - 1)
    new_y = clamp(player_world_pos[1] + vy * dt, 0, world_height - 1)
    target_tile_x, target_tile_y = int(new_x // tile_size), int(new_y // tile_size)

    # Check for rock collision
    if state.tiles[target_tile_x][target_tile_y].kind == "rock":
        current_tile_x = int(player_world_pos[0] // tile_size)
        current_tile_y = int(player_world_pos[1] // tile_size)
        if (target_tile_x, target_tile_y) != (current_tile_x, current_tile_y):
            if (target_tile_x, target_tile_y) != state.last_rock_blocked:
                state.messages.append("Rock blocks the way.")
                state.last_rock_blocked = (target_tile_x, target_tile_y)
            return

    player_world_pos[0], player_world_pos[1] = new_x, new_y
    state.player = (target_tile_x, target_tile_y)


def run(tile_size: int = TILE_SIZE) -> None:
    """Main game loop."""
    pygame.init()

    # Create virtual screen (fixed internal resolution)
    virtual_screen = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    # Create actual display window (resizable)
    screen = pygame.display.set_mode((VIRTUAL_WIDTH, VIRTUAL_HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Kemet - Desert Terraforming")

    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()

    # Create game state
    map_w, map_h = MAP_SIZE
    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Welcome to Kemet. Press H for help.")

    # Create layout (fixed virtual screen layout)
    layout = VirtualLayout.create()

    # Create camera - viewport sized to fit map area in layout
    camera = Camera()
    camera.set_world_bounds(state.width, state.height, tile_size)
    # Set viewport to match what fits in the map display area
    camera.set_viewport_size(MAP_VIEWPORT_WIDTH, MAP_VIEWPORT_HEIGHT)

    # Player position in world pixels
    player_world_pos = [
        state.player[0] * tile_size + tile_size / 2,
        state.player[1] * tile_size + tile_size / 2
    ]

    # Center camera on player
    camera.center_on(player_world_pos[0], player_world_pos[1])

    # UI state
    toolbar = get_toolbar()
    ui_state = get_ui_state()
    show_help = False
    elevation_range = calculate_elevation_range(state)

    # Scroll state
    visible_messages = (LOG_PANEL_HEIGHT - 40) // 18

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        state.update_action_timer(dt)

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if toolbar.menu_open:
                    toolbar.close_menu()
                else:
                    running = False
                continue

            # Mouse wheel scrolling
            if event.type == pygame.MOUSEWHEEL:
                scroll_dir = event.y

                if toolbar.menu_open:
                    toolbar.cycle_menu_highlight(-scroll_dir)
                else:
                    virtual_pos = screen_to_virtual(pygame.mouse.get_pos(), screen.get_size())
                    ui_state.handle_scroll(virtual_pos, scroll_dir, len(state.messages), visible_messages)
                continue

            # Mouse clicks
            if event.type == pygame.MOUSEBUTTONDOWN and event.button not in (4, 5):
                virtual_pos = screen_to_virtual(pygame.mouse.get_pos(), screen.get_size())

                # Check popup clicks first (when menu is open)
                if toolbar.menu_open:
                    option_idx = ui_state.get_popup_option_at(virtual_pos)
                    if option_idx is not None:
                        toolbar.menu_highlight_index = option_idx
                        toolbar.confirm_menu_selection()
                        continue
                    elif not ui_state.is_over_popup(virtual_pos):
                        if event.button == 1:
                            toolbar.confirm_menu_selection()
                        else:
                            toolbar.close_menu()
                        continue

                # Left click
                if event.button == 1:
                    slot = ui_state.get_toolbar_slot_at(virtual_pos, len(toolbar.tools))
                    if slot is not None:
                        if slot == toolbar.selected_index:
                            tool = toolbar.get_selected_tool()
                            if tool and tool.has_menu():
                                toolbar.toggle_menu()
                        else:
                            toolbar.close_menu()
                            toolbar.select_by_number(slot + 1)

                # Right click
                elif event.button == 3:
                    slot = ui_state.get_toolbar_slot_at(virtual_pos, len(toolbar.tools))
                    if slot is not None:
                        toolbar.select_by_number(slot + 1)
                        tool = toolbar.get_selected_tool()
                        if tool and tool.has_menu():
                            toolbar.toggle_menu()
                    elif layout.map_rect.collidepoint(virtual_pos):
                        # Right click in map area
                        tool = toolbar.get_selected_tool()
                        if tool and tool.has_menu():
                            toolbar.toggle_menu()
                continue

            # Keyboard
            if event.type == pygame.KEYDOWN:
                if event.key == HELP_KEY:
                    show_help = not show_help
                    toolbar.close_menu()
                    continue

                if toolbar.menu_open:
                    if event.key == pygame.K_w:
                        toolbar.cycle_menu_highlight(-1)
                        continue
                    elif event.key == pygame.K_s:
                        toolbar.cycle_menu_highlight(1)
                        continue
                    elif event.key == TOOL_MENU_KEY:
                        toolbar.confirm_menu_selection()
                        continue
                    elif event.key == USE_TOOL_KEY:
                        toolbar.confirm_menu_selection()
                        # Fall through to use tool

                if event.key in TOOL_KEYS:
                    toolbar.select_by_number(TOOL_KEYS[event.key])
                    continue

                if state.is_busy():
                    continue

                if event.key == REST_KEY:
                    issue(state, "end", [])
                elif event.key == TOOL_MENU_KEY:
                    tool = toolbar.get_selected_tool()
                    if tool and tool.has_menu():
                        toolbar.toggle_menu()
                    else:
                        state.messages.append("This tool has no options.")
                elif event.key == INTERACT_KEY:
                    issue(state, "collect", [])
                elif event.key == USE_TOOL_KEY:
                    tool = toolbar.get_selected_tool()
                    if tool:
                        action, args = tool.get_action()
                        issue(state, action, args)
                        if action in ("terrain", "raise", "lower"):
                            elevation_range = calculate_elevation_range(state)

        # Movement (when menu closed)
        if not toolbar.menu_open:
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
            update_player_position(state, player_world_pos, (vx, vy), dt, tile_size)

        # Camera follows player
        camera.follow(player_world_pos[0], player_world_pos[1])

        # Simulation tick
        tick_timer = getattr(state, '_tick_timer', 0.0) + dt
        if tick_timer >= TICK_INTERVAL:
            simulate_tick(state)
            tick_timer -= TICK_INTERVAL
        state._tick_timer = tick_timer

        # Update visible messages count
        if ui_state.log_panel_rect:
            visible_messages = (ui_state.log_panel_rect.height - 40) // 18

        # Render to virtual screen
        render_to_virtual_screen(
            virtual_screen, font, state, camera, tile_size, elevation_range,
            (player_world_pos[0], player_world_pos[1]),
            toolbar, ui_state, layout, show_help
        )

        # Scale and blit to actual screen
        blit_virtual_to_screen(virtual_screen, screen)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
