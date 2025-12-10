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
from player import update_player_movement
from tools import get_toolbar, Toolbar
from ui_state import (
    get_ui_state,
    UIState,
    VIRTUAL_WIDTH,
    VIRTUAL_HEIGHT,
    LOG_PANEL_HEIGHT,
)
from keybindings import (
    CONTROL_DESCRIPTIONS,
    TOOL_KEYS,
    USE_TOOL_KEY,
    INTERACT_KEY,
    TOOL_MENU_KEY,
    REST_KEY,
    HELP_KEY,
)
from config import (
    TILE_SIZE,
    SUB_TILE_SIZE,
    MOVE_SPEED,
    TICK_INTERVAL,
    PROFILE_WIDTH,
    PROFILE_HEIGHT,
    PROFILE_MARGIN,
    TOOLBAR_HEIGHT,
    MAP_SIZE,
    FONT_SIZE,
    SUBGRID_SIZE,
)
from render import (
    calculate_elevation_range,
    render_map_viewport,
    render_player,
    render_night_overlay,
    render_hud,
    render_inventory,
    render_soil_profile,
    render_toolbar,
    render_help_overlay,
    render_event_log,
)
from render.map import render_interaction_highlights


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

    return vx, vy


def virtual_to_world(
    virtual_pos: Tuple[int, int],
    ui_state: UIState,
    camera: Camera,
) -> Optional[Tuple[float, float]]:
    """
    Transform virtual screen coordinates to world coordinates.
    Returns None if position is outside the map viewport.
    """
    if not ui_state.map_rect.collidepoint(virtual_pos):
        return None

    # Position within the map viewport
    vp_x = virtual_pos[0] - ui_state.map_rect.x
    vp_y = virtual_pos[1] - ui_state.map_rect.y

    # Scale from viewport to camera viewport size
    scale_x = camera.viewport_width / ui_state.map_rect.width
    scale_y = camera.viewport_height / ui_state.map_rect.height

    cam_vp_x = vp_x * scale_x
    cam_vp_y = vp_y * scale_y

    # Convert to world coordinates
    world_x, world_y = camera.viewport_to_world(cam_vp_x, cam_vp_y)

    return world_x, world_y


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
    show_help: bool,
) -> None:
    """Render everything to the virtual screen at fixed resolution."""
    virtual_screen.fill((20, 20, 25))

    # 1. Render map viewport (tiles, structures, features)
    map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))
    render_map_viewport(map_surface, font, state, camera, tile_size, elevation_range)

    # Render interaction highlights (before player, after tiles)
    render_interaction_highlights(
        map_surface,
        camera,
        state.player_state.position,  # Sub-grid coordinates
        ui_state.target_subsquare,
        toolbar.get_selected_tool(),
        state,
    )

    render_player(map_surface, state, camera, player_world_pos, tile_size)
    render_night_overlay(map_surface, state.heat)

    # Scale map surface to fit the ui_state's map rect
    scaled_map = pygame.transform.scale(map_surface, ui_state.map_rect.size)
    virtual_screen.blit(scaled_map, ui_state.map_rect.topleft)

    # 2. Render sidebar elements
    sidebar_x = ui_state.sidebar_rect.x + 12
    y_offset = 12

    # HUD
    render_hud(virtual_screen, font, state, sidebar_x, y_offset)

    # Soil profile (show tile at player's current position)
    soil_x = ui_state.sidebar_rect.x + PROFILE_MARGIN
    soil_y = 180  # Below HUD
    px, py = state.player_state.tile_position
    render_soil_profile(virtual_screen, font, state.tiles[px][py], (soil_x, soil_y), PROFILE_WIDTH, PROFILE_HEIGHT - 22)

    # Inventory
    inv_w, inv_h = 180, 140
    inv_x = VIRTUAL_WIDTH - inv_w - 12
    inv_y = ui_state.map_rect.bottom - inv_h - 12
    render_inventory(virtual_screen, font, state, (inv_x, inv_y), inv_w, inv_h)

    # 3. Render toolbar
    render_toolbar(virtual_screen, font, toolbar, ui_state.toolbar_rect.topleft,
                   ui_state.toolbar_rect.width, TOOLBAR_HEIGHT, ui_state)

    # Update tool slot width for mouse interaction
    ui_state.tool_slot_width = ui_state.toolbar_rect.width // len(toolbar.tools) if toolbar.tools else 0

    # 4. Render log panel
    pygame.draw.line(virtual_screen, (80, 80, 80),
                     (0, ui_state.log_panel_rect.y),
                     (VIRTUAL_WIDTH, ui_state.log_panel_rect.y), 2)

    log_x, log_y = 12, ui_state.log_panel_rect.y + 8
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

    # UI state (includes fixed layout regions)
    toolbar = get_toolbar()
    ui_state = get_ui_state()

    # Create camera - viewport sized to fit map area in layout
    camera = Camera()
    camera.set_world_bounds(state.width, state.height, tile_size)
    camera.set_viewport_size(ui_state.map_rect.width, ui_state.map_rect.height)

    # World dimensions in sub-squares (for movement bounds and cursor clamping)
    world_sub_width = state.width * SUBGRID_SIZE
    world_sub_height = state.height * SUBGRID_SIZE

    # Movement speed in sub-squares per second (not pixels)
    move_speed_subsquares = MOVE_SPEED / SUB_TILE_SIZE

    # Center camera on player
    player_px, player_py = state.player_state.world_pixel_pos
    camera.center_on(player_px, player_py)
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
                    elif ui_state.map_rect.collidepoint(virtual_pos):
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
                vy -= move_speed_subsquares
            if keys[pygame.K_s]:
                vy += move_speed_subsquares
            if keys[pygame.K_a]:
                vx -= move_speed_subsquares
            if keys[pygame.K_d]:
                vx += move_speed_subsquares

            def is_blocked(tx: int, ty: int) -> bool:
                return state.tiles[tx][ty].kind == "rock"

            update_player_movement(
                state.player_state, (vx, vy), dt,
                world_sub_width, world_sub_height, is_blocked
            )

        # Camera follows player (get pixel position from player state)
        player_px, player_py = state.player_state.world_pixel_pos
        camera.follow(player_px, player_py)

        # Update cursor tracking for interaction highlights
        mouse_screen_pos = pygame.mouse.get_pos()
        virtual_pos = screen_to_virtual(mouse_screen_pos, screen.get_size())
        ui_state.update_cursor(
            virtual_pos,
            camera,
            state.player_state.position,
            world_sub_width,
            world_sub_height,
        )

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
            state.player_state.world_pixel_pos,
            toolbar, ui_state, show_help
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
