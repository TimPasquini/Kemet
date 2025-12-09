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
    SIDEBAR_WIDTH,
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
    render_map,
    render_player,
    render_hud,
    render_inventory,
    render_soil_profile,
    render_toolbar,
    render_help_overlay,
    render_night_overlay,
    render_event_log,
)

MapSize = Tuple[int, int]


def render(
    virtual_screen,
    font,
    state: GameState,
    tile_size: int,
    player_px: Tuple[float, float],
    toolbar: Toolbar,
    show_help: bool,
    elevation_range: Optional[Tuple[float, float]],
    ui_state: UIState,
) -> None:
    """Main render function that composes all rendering components."""
    virtual_screen.fill((20, 20, 25))
    map_width = state.width * tile_size
    map_height = state.height * tile_size

    # Render map and player
    render_map(virtual_screen, font, state, tile_size, elevation_range)
    render_player(virtual_screen, state, player_px, tile_size)

    # Render night overlay (before HUD so it only affects map)
    render_night_overlay(virtual_screen, state, map_width, map_height)

    # Render HUD panels
    hud_x = map_width + 12
    render_hud(virtual_screen, font, state, hud_x, 12)

    # Render soil profile
    x, y = state.player
    tile = state.tiles[x][y]
    soil_x = virtual_screen.get_width() - PROFILE_WIDTH - PROFILE_MARGIN
    render_soil_profile(virtual_screen, font, tile, (soil_x, 12 + 22), PROFILE_WIDTH, PROFILE_HEIGHT - 22)

    # Render inventory
    inv_w, inv_h = 180, 140
    inv_x = virtual_screen.get_width() - inv_w - 12
    inv_y = clamp(map_height - inv_h - 12, 12, 9999)
    render_inventory(virtual_screen, font, state, (inv_x, int(inv_y)), inv_w, inv_h)

    # Render toolbar and store bounds for mouse interaction
    render_toolbar(virtual_screen, font, toolbar, (0, map_height), map_width, TOOLBAR_HEIGHT, ui_state)
    ui_state.toolbar_rect = pygame.Rect(0, map_height, map_width, TOOLBAR_HEIGHT)
    ui_state.tool_slot_width = map_width // len(toolbar.tools) if toolbar.tools else 0

    # Render log panel area
    log_panel_y = map_height + TOOLBAR_HEIGHT
    log_panel_height = virtual_screen.get_height() - log_panel_y
    pygame.draw.line(virtual_screen, (80, 80, 80), (0, log_panel_y), (virtual_screen.get_width(), log_panel_y), 2)

    # Store log panel bounds for scroll detection
    ui_state.log_panel_rect = pygame.Rect(0, log_panel_y, virtual_screen.get_width(), log_panel_height)

    log_x, log_y = 12, log_panel_y + 8
    if show_help:
        render_help_overlay(virtual_screen, font, CONTROL_DESCRIPTIONS, (log_x, log_y), virtual_screen.get_width() - 24, log_panel_height - 16)
    else:
        render_event_log(virtual_screen, font, state, (log_x, log_y), log_panel_height, ui_state.log_scroll_offset)


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
    player_px: List[float],
    vel: Tuple[float, float],
    dt: float,
    tile_size: int,
) -> None:
    """Update player pixel position and tile position based on velocity."""
    if state.is_busy():
        return

    if vel == (0.0, 0.0):
        return

    vx, vy = vel
    if vx != 0.0 and vy != 0.0:
        vx *= DIAGONAL_FACTOR
        vy *= DIAGONAL_FACTOR

    new_x = clamp(player_px[0] + vx * dt, 0, state.width * tile_size - 1)
    new_y = clamp(player_px[1] + vy * dt, 0, state.height * tile_size - 1)
    target_tile_x, target_tile_y = int(new_x // tile_size), int(new_y // tile_size)

    # Check for rock collision
    if state.tiles[target_tile_x][target_tile_y].kind == "rock":
        current_tile_x, current_tile_y = int(player_px[0] // tile_size), int(player_px[1] // tile_size)
        if (target_tile_x, target_tile_y) != (current_tile_x, current_tile_y):
            if (target_tile_x, target_tile_y) != state.last_rock_blocked:
                state.messages.append("Rock blocks the way.")
                state.last_rock_blocked = (target_tile_x, target_tile_y)
            return

    player_px[0], player_px[1] = new_x, new_y
    state.player = (target_tile_x, target_tile_y)


def transform_mouse_pos(pos: Tuple[int, int], screen_size: Tuple[int, int], virtual_size: Tuple[int, int]) -> Tuple[int, int]:
    """Transforms mouse coordinates from screen space to virtual surface space."""
    screen_w, screen_h = screen_size
    virtual_w, virtual_h = virtual_size
    x, y = pos

    # Calculate scaling factor and letterbox/pillarbox offsets
    scale = min(screen_w / virtual_w, screen_h / virtual_h)
    scaled_w, scaled_h = virtual_w * scale, virtual_h * scale
    offset_x = (screen_w - scaled_w) / 2
    offset_y = (screen_h - scaled_h) / 2

    # Transform coordinates
    transformed_x = int((x - offset_x) / scale)
    transformed_y = int((y - offset_y) / scale)

    return transformed_x, transformed_y


def run(window_size: MapSize = MAP_SIZE, tile_size: int = TILE_SIZE) -> None:
    """Main game loop."""
    pygame.init()

    # Define a fixed base resolution for the game UI and logic
    map_w, map_h = window_size
    base_width = map_w * tile_size + SIDEBAR_WIDTH
    base_height = map_h * tile_size + TOOLBAR_HEIGHT + 120
    virtual_screen = pygame.Surface((base_width, base_height))

    screen = pygame.display.set_mode((base_width, base_height), pygame.RESIZABLE)
    pygame.display.set_caption("Kemet - Desert Terraforming")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()

    state = build_initial_state(width=map_w, height=map_h)
    state.messages.append("Welcome to Kemet. Press H for help. 1-9 select tools, R opens options (W/S to navigate), F to use.")

    player_px = [state.player[0] * tile_size + tile_size / 2, state.player[1] * tile_size + tile_size / 2]
    tick_timer = 0.0
    toolbar = get_toolbar()
    ui_state = get_ui_state()
    show_help = False
    elevation_range = calculate_elevation_range(state)

    # Calculate visible message count for scroll limits
    log_panel_height = 120 - 16  # Approximate, will be updated in render
    visible_messages = (log_panel_height - 40) // 18

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        state.update_action_timer(dt)

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)

            # Mouse wheel scrolling
            elif event.type == pygame.MOUSEWHEEL:
                scroll_dir = event.y  # positive = up, negative = down

                # If menu is open, scroll always controls the menu highlight
                if toolbar.menu_open:
                    # Scroll up = previous option, scroll down = next option
                    toolbar.cycle_menu_highlight(-scroll_dir)
                else:
                    # Otherwise scroll the event log
                    mouse_pos = transform_mouse_pos(pygame.mouse.get_pos(), screen.get_size(), virtual_screen.get_size())
                    ui_state.handle_scroll(mouse_pos, scroll_dir, len(state.messages), visible_messages)

            # Mouse button clicks (ignore scroll wheel buttons 4/5, handled by MOUSEWHEEL)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button not in (4, 5):
                mouse_pos = transform_mouse_pos(pygame.mouse.get_pos(), screen.get_size(), virtual_screen.get_size())

                # Check popup clicks first (when menu is open)
                if toolbar.menu_open:
                    option_idx = ui_state.get_popup_option_at(mouse_pos)
                    if option_idx is not None:
                        # Click on option: set highlight and confirm
                        toolbar.menu_highlight_index = option_idx
                        toolbar.confirm_menu_selection()
                        continue
                    # Click outside popup - left click confirms, right click cancels
                    elif not ui_state.is_over_popup(mouse_pos):
                        if event.button == 1:  # Left click confirms highlighted option
                            toolbar.confirm_menu_selection()
                        else:  # Right click cancels
                            toolbar.close_menu()
                        continue

                # Left click on toolbar to select tool or toggle menu
                if event.button == 1:  # Left click
                    slot = ui_state.get_toolbar_slot_at(mouse_pos, len(toolbar.tools))
                    if slot is not None:
                        if slot == toolbar.selected_index:
                            # Clicking already-selected tool toggles its menu
                            tool = toolbar.get_selected_tool()
                            if tool and tool.has_menu():
                                toolbar.toggle_menu()
                        else:
                            # Clicking different tool selects it and closes menu
                            toolbar.close_menu()
                            toolbar.select_by_number(slot + 1)

                # Right click to toggle tool options menu
                elif event.button == 3:  # Right click
                    # Check if clicking on toolbar first
                    slot = ui_state.get_toolbar_slot_at(mouse_pos, len(toolbar.tools))
                    if slot is not None:
                        # Right click on toolbar selects that tool and opens menu
                        toolbar.select_by_number(slot + 1)
                        tool = toolbar.get_selected_tool()
                        if tool and tool.has_menu():
                            toolbar.toggle_menu()
                    else:
                        # Right click in map area toggles menu for selected tool
                        map_width = state.width * tile_size
                        map_height = state.height * tile_size
                        if mouse_pos[0] < map_width and mouse_pos[1] < map_height:
                            tool = toolbar.get_selected_tool()
                            if tool and tool.has_menu():
                                toolbar.toggle_menu()

            elif event.type == pygame.KEYDOWN:
                # Help toggle works even when busy
                if event.key == HELP_KEY:
                    show_help = not show_help
                    toolbar.close_menu()
                    continue

                # Tool menu navigation when menu is open
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
                    elif event.key == pygame.K_ESCAPE:
                        toolbar.close_menu()
                        continue
                    elif event.key == USE_TOOL_KEY:
                        toolbar.confirm_menu_selection()
                        # Fall through to use tool

                # Tool selection
                if event.key in TOOL_KEYS:
                    tool_num = TOOL_KEYS[event.key]
                    toolbar.select_by_number(tool_num)
                    continue

                # Block other actions while busy
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

        # Handle continuous movement (disabled when menu is open)
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
            update_player_position(state, player_px, (vx, vy), dt, tile_size)

        # Continuous world simulation tick
        tick_timer += dt
        if tick_timer >= TICK_INTERVAL:
            simulate_tick(state)
            tick_timer -= TICK_INTERVAL

        # Reset scroll when new messages arrive (user is at bottom)
        if ui_state.log_scroll_offset == 0:
            pass  # Already at bottom, new messages will show
        # Update visible message count from actual log panel
        if ui_state.log_panel_rect:
            visible_messages = (ui_state.log_panel_rect.height - 40) // 18

        # --- Main Rendering ---
        # 1. Render all game elements to the off-screen virtual surface
        render(virtual_screen, font, state, tile_size, (player_px[0], player_px[1]), toolbar, show_help, elevation_range, ui_state)

        # 2. Scale the virtual surface to fit the actual window, preserving aspect ratio
        screen_w, screen_h = screen.get_size()
        virtual_w, virtual_h = virtual_screen.get_size()
        scale = min(screen_w / virtual_w, screen_h / virtual_h)
        scaled_surf = pygame.transform.smoothscale(virtual_screen, (int(virtual_w * scale), int(virtual_h * scale)))
        dest_rect = scaled_surf.get_rect(center=(screen_w / 2, screen_h / 2))

        # 3. Blit the scaled surface to the screen
        screen.fill((0, 0, 0))  # Black bars for letterboxing
        screen.blit(scaled_surf, dest_rect)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
