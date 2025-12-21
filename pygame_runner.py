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
    MOVE_SPEED,
    TICK_INTERVAL,
    SUBGRID_SIZE,
    MAP_SIZE,
)
from render.config import (
    VIRTUAL_WIDTH,
    VIRTUAL_HEIGHT,
    LOG_PANEL_HEIGHT,
    PROFILE_WIDTH,
    PROFILE_HEIGHT,
    PROFILE_MARGIN,
    TOOLBAR_HEIGHT,
    FONT_SIZE,
    COLOR_BG_DARK,
    TILE_SIZE,
    SUB_TILE_SIZE,
)
from subgrid import subgrid_to_tile, get_subsquare_index
from render import (
    render_map_viewport,
    render_static_background,
    render_night_overlay,
    render_hud,
    render_inventory,
    render_soil_profile,
    render_toolbar,
    render_help_overlay,
    render_event_log,
)
from render.map import render_interaction_highlights, redraw_background_rect
from render.player_renderer import render_player
from render.minimap import render_minimap


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


def update_dirty_background(
    background_surface: pygame.Surface,
    state: GameState,
    font
) -> pygame.Surface:
    """Redraw dirty portions of the background surface.

    Args:
        background_surface: The cached background surface to update
        state: Game state with dirty_subsquares set
        font: Font for rendering

    Returns:
        Updated background surface
    """
    if not state.dirty_subsquares:
        return background_surface

    # Redraw only the dirty sub-squares
    for sub_x, sub_y in state.dirty_subsquares:
        rect = pygame.Rect(
            sub_x * SUB_TILE_SIZE,
            sub_y * SUB_TILE_SIZE,
            SUB_TILE_SIZE,
            SUB_TILE_SIZE
        )
        redraw_background_rect(background_surface, state, font, rect)

    state.dirty_subsquares.clear()
    return background_surface

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
    background_surface: pygame.Surface = None,
    map_surface: pygame.Surface = None,
) -> None:
    """Render everything to the virtual screen at fixed resolution."""
    virtual_screen.fill(COLOR_BG_DARK)

    # 1. Render map viewport (tiles, structures, features)
    # map_surface is now passed in and reused to avoid per-frame allocation
    # We pass the scaled tile size to the renderer so it draws at the correct zoom level
    scaled_tile_size = int(tile_size * camera.zoom)
    scaled_sub_tile_size = int(scaled_tile_size / SUBGRID_SIZE)
    
    # Ensure map surface is large enough for the viewport
    if map_surface.get_width() != camera.viewport_width or map_surface.get_height() != camera.viewport_height:
        # This shouldn't happen often if camera viewport is fixed to layout
        map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))

    render_map_viewport(map_surface, font, state, camera, scaled_tile_size, elevation_range, background_surface)

    # Render interaction highlights (before player, after tiles)
    render_interaction_highlights(
        map_surface,
        camera,
        state.player_state.position,  # Sub-grid coordinates
        ui_state,
        toolbar.get_selected_tool(),
        scaled_sub_tile_size,
    )

    render_player(map_surface, state, camera, player_world_pos, scaled_tile_size)
    render_night_overlay(map_surface, state.heat)

    # Scale map surface to fit the ui_state's map rect
    scaled_map = pygame.transform.scale(map_surface, ui_state.map_rect.size)
    virtual_screen.blit(scaled_map, ui_state.map_rect.topleft)

    # 2. Render sidebar elements
    # Two-column layout:
    # Left col: Text info (Env, Atmos, Tile, Inv)
    # Right col: Soil profile
    sidebar_x = ui_state.sidebar_rect.x
    y_offset = 12
    
    col1_x = sidebar_x + 12
    col2_x = sidebar_x + 160  # 12 (margin) + 130 (text width) + ~18 (gap)

    # Minimap (Top of Col 1)
    minimap_height = 100
    minimap_rect = pygame.Rect(col1_x, y_offset, 130, minimap_height)
    render_minimap(virtual_screen, state, camera, minimap_rect)

    # Column 1: HUD Stack + Inventory (Below Minimap)
    hud_bottom = render_hud(virtual_screen, font, state, col1_x, y_offset + minimap_height + 10)
    render_inventory(virtual_screen, font, state, col1_x, hud_bottom)

    # Column 2: Soil profile (show sub-square at cursor target, or player position if no target)
    soil_y = y_offset + 22  # Offset to align top of header box with text in col 1
    profile_sub_pos = state.target_subsquare if state.target_subsquare else state.player_state.position
    profile_tile_pos = subgrid_to_tile(profile_sub_pos[0], profile_sub_pos[1])
    profile_tile = state.tiles[profile_tile_pos[0]][profile_tile_pos[1]]
    local_x, local_y = get_subsquare_index(profile_sub_pos[0], profile_sub_pos[1])
    profile_subsquare = profile_tile.subgrid[local_x][local_y]
    
    # Calculate available height for the soil profile (fill down to bottom margin)
    soil_height = ui_state.log_panel_rect.y - soil_y - 12  # Stop at log panel line, -12 margin
    profile_water = state.water_grid[profile_sub_pos]
    render_soil_profile(virtual_screen, font, profile_tile, profile_subsquare, (col2_x, soil_y), PROFILE_WIDTH, soil_height, profile_water)

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


def issue(state: GameState, cmd: str, args: List[str], target_subsquare: Optional[Tuple[int, int]] = None) -> None:
    """Issues a command and sets the player's action timer.

    Args:
        state: Game state
        cmd: Command to execute
        args: Command arguments
        target_subsquare: Target position in sub-grid coords (or None for player position)
    """
    if state.is_busy():
        return

    # Set target for action
    state.set_target(target_subsquare)

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

    # Generate the static background surface for the first time
    background_surface = render_static_background(state, font)

    # UI state (includes fixed layout regions)
    toolbar = get_toolbar()
    ui_state = get_ui_state()

    # Create camera - viewport sized to fit map area in layout
    camera = Camera()
    camera.set_world_bounds(state.width, state.height, tile_size)
    camera.set_viewport_size(ui_state.map_rect.width, ui_state.map_rect.height)

    # Pre-allocate map surface to avoid per-frame allocation (~1-2MB saved per frame)
    map_surface = pygame.Surface((camera.viewport_width, camera.viewport_height))

    # World dimensions in sub-squares (for movement bounds and cursor clamping)
    world_sub_width = state.width * SUBGRID_SIZE
    world_sub_height = state.height * SUBGRID_SIZE

    # Movement speed in sub-squares per second (not pixels)
    move_speed_subsquares = MOVE_SPEED / SUB_TILE_SIZE

    # Center camera on player
    player_px = state.player_state.smooth_x * SUB_TILE_SIZE
    player_py = state.player_state.smooth_y * SUB_TILE_SIZE
    camera.center_on(player_px, player_py)
    show_help = False
    # elevation_range is now cached on state and retrieved via get_elevation_range()

    # Scroll state
    visible_messages = (LOG_PANEL_HEIGHT - 40) // 18

    # Track last mouse position to avoid redundant cursor updates
    last_mouse_pos: Tuple[int, int] = (-1, -1)

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
                    # Try to scroll UI first (e.g. log panel)
                    if not ui_state.handle_scroll(virtual_pos, scroll_dir, len(state.messages), visible_messages):
                        # If UI didn't consume the scroll, zoom the camera
                        # scroll_dir is usually 1 (up/in) or -1 (down/out)
                        zoom_speed = 0.1
                        camera.set_zoom(camera.zoom + (scroll_dir * zoom_speed))
                continue
                
            # Zoom controls (Plus/Minus keys)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_EQUALS or event.key == pygame.K_PLUS: # +
                    camera.set_zoom(camera.zoom + 0.25)
                    continue
                elif event.key == pygame.K_MINUS: # -
                    camera.set_zoom(camera.zoom - 0.25)
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
                    elif ui_state.map_rect.collidepoint(virtual_pos):
                        # Left click in map area - trigger selected tool
                        tool = toolbar.get_selected_tool()
                        if tool:
                            action, args = tool.get_action()
                            issue(state, action, args, ui_state.target_subsquare)
                            # Elevation range cache is invalidated automatically by terrain actions

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
                    issue(state, "collect", [], ui_state.target_subsquare)
                elif event.key == USE_TOOL_KEY:
                    tool = toolbar.get_selected_tool()
                    if tool:
                        action, args = tool.get_action()
                        issue(state, action, args, ui_state.target_subsquare)
                        # Elevation range cache is invalidated automatically by terrain actions

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

            def is_blocked(sub_x: int, sub_y: int) -> bool:
                """Check if a subsquare is blocked for movement."""
                from subgrid import subgrid_to_tile, get_subsquare_index

                tile_x, tile_y = subgrid_to_tile(sub_x, sub_y)
                tile = state.tiles[tile_x][tile_y]

                # REMOVED: Block on rock tiles
                # Rock tiles are now passable terrain
                
                # Check if this specific subsquare has a structure
                local_x, local_y = get_subsquare_index(sub_x, sub_y)
                subsquare = tile.subgrid[local_x][local_y]
                if subsquare.structure_id is not None:
                    return True

                return False

            update_player_movement(
                state.player_state, (vx, vy), dt,
                world_sub_width, world_sub_height, is_blocked
            )

        # Camera follows player (get pixel position from player state)
        player_px = state.player_state.smooth_x * SUB_TILE_SIZE
        player_py = state.player_state.smooth_y * SUB_TILE_SIZE
        camera.follow(player_px, player_py)

        # Update cursor tracking only when mouse has moved (avoids per-frame recalculation)
        mouse_screen_pos = pygame.mouse.get_pos()
        if mouse_screen_pos != last_mouse_pos:
            last_mouse_pos = mouse_screen_pos
            virtual_pos = screen_to_virtual(mouse_screen_pos, screen.get_size())
            ui_state.update_cursor(
                virtual_pos,
                camera,
                state,
                toolbar.get_selected_tool(),
            )
            # Sync target to game state for rendering and commands
            state.set_target(ui_state.target_subsquare)

        # Simulation tick
        state._tick_timer += dt
        if state._tick_timer >= TICK_INTERVAL:
            simulate_tick(state)
            state._tick_timer -= TICK_INTERVAL

        # Update dirty rects on the background surface
        background_surface = update_dirty_background(background_surface, state, font)

        # Update visible messages count
        if ui_state.log_panel_rect:
            visible_messages = (ui_state.log_panel_rect.height - 40) // 18

        # Render to virtual screen
        render_to_virtual_screen(
            virtual_screen, font, state, camera, tile_size, state.get_elevation_range(),
            (player_px, player_py),
            toolbar, ui_state, show_help, background_surface, map_surface
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
