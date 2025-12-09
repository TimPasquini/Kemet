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


@dataclass
class UILayout:
    """Calculates and holds the rectangles for all UI components."""
    screen_width: int
    screen_height: int

    map_rect: pygame.Rect
    sidebar_rect: pygame.Rect
    log_panel_rect: pygame.Rect
    toolbar_rect: pygame.Rect

    @classmethod
    def from_screen_size(cls, screen_size: Tuple[int, int], map_pixel_size: Tuple[int, int]) -> UILayout:
        sw, sh = screen_size
        mw, mh = map_pixel_size
        map_rect = pygame.Rect(0, 0, mw, mh)
        sidebar_rect = pygame.Rect(mw, 0, sw - mw, sh)
        toolbar_rect = pygame.Rect(0, mh, mw, TOOLBAR_HEIGHT)
        log_panel_rect = pygame.Rect(0, mh + TOOLBAR_HEIGHT, sw, sh - mh - TOOLBAR_HEIGHT)
        return cls(sw, sh, map_rect, sidebar_rect, log_panel_rect, toolbar_rect)


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


def run(tile_size: int = TILE_SIZE) -> None:
    """Main game loop."""
    pygame.init()

    # Define a standard base resolution (16:9) and create the virtual surface
    base_width, base_height = 1280, 720
    virtual_screen = pygame.Surface((base_width, base_height))
    
    # The map size is now fixed based on our ideal layout, not the window.
    # The map view will scale; the UI will not.
    map_w, map_h = MAP_SIZE
    state = build_initial_state(width=map_w, height=map_h)

    # Set up the actual display window
    screen = pygame.display.set_mode((base_width, base_height), pygame.RESIZABLE)
    pygame.display.set_caption("Kemet - Desert Terraforming")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()

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
            # The RESIZABLE flag allows the window to be resized by the user.
            # We don't need to do anything here; the main loop will handle the new size.

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

        # --- Dynamic Layout Calculation ---
        screen_w, screen_h = screen.get_size()
        
        # 1. Calculate the available area for the map
        available_width = max(1, screen_w - SIDEBAR_WIDTH)
        available_height = max(1, screen_h - TOOLBAR_HEIGHT - 120)

        # 2. Determine map size that fits available area while preserving aspect ratio
        map_aspect_ratio = state.width / state.height
        
        map_pixel_width = available_width
        map_pixel_height = int(map_pixel_width / map_aspect_ratio)
        if map_pixel_height > available_height:
            map_pixel_height = available_height
            map_pixel_width = int(map_pixel_height * map_aspect_ratio)
        layout = UILayout.from_screen_size(screen.get_size(), (map_pixel_width, map_pixel_height))

        # --- Rendering ---
        screen.fill((20, 20, 25))

        # 1. Render the map to a separate surface and scale it to fit its area
        map_surface = pygame.Surface((state.width * tile_size, state.height * tile_size))
        render_map(map_surface, font, state, tile_size, elevation_range)
        render_player(map_surface, state, player_px, tile_size)
        render_night_overlay(map_surface, state, map_surface.get_width(), map_surface.get_height())
        
        scaled_map = pygame.transform.scale(map_surface, layout.map_rect.size)
        screen.blit(scaled_map, layout.map_rect.topleft)

        # 2. Render all UI elements directly to the screen at native resolution
        # HUD (top-right)
        render_hud(screen, font, state, layout.sidebar_rect.x + 12, 12)

        # Soil Profile (below HUD)
        soil_x = layout.sidebar_rect.x + PROFILE_MARGIN
        render_soil_profile(screen, font, state.tiles[state.player[0]][state.player[1]], (soil_x, 12 + 22), PROFILE_WIDTH, PROFILE_HEIGHT - 22)

        # Inventory (bottom-right)
        inv_w, inv_h = 180, 140
        inv_x = layout.screen_width - inv_w - 12
        inv_y = clamp(layout.map_rect.bottom - inv_h - 12, 12, 9999)
        render_inventory(screen, font, state, (inv_x, int(inv_y)), inv_w, inv_h)

        # Toolbar and Log Panel (bottom)
        render_toolbar(screen, font, toolbar, layout.toolbar_rect.topleft, layout.toolbar_rect.width, TOOLBAR_HEIGHT, ui_state)
        if show_help:
            render_help_overlay(screen, font, CONTROL_DESCRIPTIONS, (layout.log_panel_rect.x + 12, layout.log_panel_rect.y + 8), layout.log_panel_rect.width - 24, layout.log_panel_rect.height - 16)
        else:
            render_event_log(screen, font, state, (layout.log_panel_rect.x + 12, layout.log_panel_rect.y + 8), layout.log_panel_rect.height, ui_state.log_scroll_offset)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
