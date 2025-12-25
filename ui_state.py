# ui_state.py
"""
UI state management for pygame frontend.

Tracks layout regions, scroll positions, hover states, click regions,
and cursor/target tracking for the sub-grid interaction system.
Keeps UI state separate from game state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, Optional, Callable, List, TYPE_CHECKING

import pygame

from config import INTERACTION_RANGE, GRID_WIDTH, GRID_HEIGHT
from render.config import (
    VIRTUAL_WIDTH,
    VIRTUAL_HEIGHT,
    SIDEBAR_WIDTH,
    TOOLBAR_HEIGHT,
    LOG_PANEL_HEIGHT,
    POPUP_OPTION_HEIGHT,
)
from utils import clamp_to_range, clamp_to_bounds

if TYPE_CHECKING:
    from camera import Camera
    from main import GameState
    from tools import Tool

# Layout constants derived from render config
MAP_VIEWPORT_WIDTH = VIRTUAL_WIDTH - SIDEBAR_WIDTH
MAP_VIEWPORT_HEIGHT = VIRTUAL_HEIGHT - TOOLBAR_HEIGHT - LOG_PANEL_HEIGHT


@dataclass
class ClickRegion:
    """A clickable region on screen."""
    rect: pygame.Rect
    on_click: Callable[[], None]
    on_hover: Optional[Callable[[], None]] = None


@dataclass
class UIState:
    """
    Manages UI layout and transient state.

    Layout regions are fixed at creation time. Other state (scroll, hover, etc.)
    changes during gameplay.
    """
    # Fixed layout regions (set once at init)
    map_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, MAP_VIEWPORT_WIDTH, MAP_VIEWPORT_HEIGHT))
    sidebar_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(MAP_VIEWPORT_WIDTH, 0, SIDEBAR_WIDTH, VIRTUAL_HEIGHT))
    toolbar_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, MAP_VIEWPORT_HEIGHT, MAP_VIEWPORT_WIDTH, TOOLBAR_HEIGHT))
    log_panel_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, MAP_VIEWPORT_HEIGHT + TOOLBAR_HEIGHT, VIRTUAL_WIDTH, LOG_PANEL_HEIGHT))

    # Toolbar state
    tool_slot_width: int = 0

    # Event log scrolling
    log_scroll_offset: int = 0  # 0 = showing most recent, positive = scrolled up

    # Clickable regions (rebuilt each frame)
    click_regions: List[ClickRegion] = field(default_factory=list)

    # Hover state
    hovered_region: Optional[ClickRegion] = None

    # Tool options popup bounds (set during render when menu is open)
    popup_rect: Optional[pygame.Rect] = None
    popup_option_height: int = POPUP_OPTION_HEIGHT
    popup_option_count: int = 0

    # Cursor tracking for grid interaction system
    hovered_cell: Optional[Tuple[int, int]] = None  # Raw grid cell under cursor
    target_cell: Optional[Tuple[int, int]] = None   # Clamped to interaction range
    is_valid_target: bool = True                    # Is the target valid for the current tool?

    def clear_regions(self) -> None:
        """Clear all click regions (called at start of each frame)."""
        self.click_regions.clear()
        self.hovered_region = None

    def add_click_region(self, rect: pygame.Rect, on_click: Callable[[], None],
                         on_hover: Optional[Callable[[], None]] = None) -> None:
        """Register a clickable region."""
        self.click_regions.append(ClickRegion(rect, on_click, on_hover))

    def handle_mouse_motion(self, pos: Tuple[int, int]) -> None:
        """Update hover state based on mouse position."""
        self.hovered_region = None
        for region in self.click_regions:
            if region.rect.collidepoint(pos):
                self.hovered_region = region
                if region.on_hover:
                    region.on_hover()
                break

    def handle_mouse_click(self, pos: Tuple[int, int], button: int) -> bool:
        """
        Handle mouse click at position. Returns True if a region was clicked.
        button: 1=left, 2=middle, 3=right, 4=scroll up, 5=scroll down
        """
        for region in self.click_regions:
            if region.rect.collidepoint(pos):
                region.on_click()
                return True
        return False

    def handle_scroll(self, pos: Tuple[int, int], direction: int, total_messages: int, visible_count: int) -> bool:
        """
        Handle mouse scroll. direction: positive=up, negative=down.
        Returns True if scroll was handled.
        """
        # Check if mouse is over log panel
        if self.log_panel_rect and self.log_panel_rect.collidepoint(pos):
            max_scroll = max(0, total_messages - visible_count)
            if direction > 0:  # Scroll up (show older)
                self.log_scroll_offset = min(self.log_scroll_offset + 1, max_scroll)
            else:  # Scroll down (show newer)
                self.log_scroll_offset = max(self.log_scroll_offset - 1, 0)
            return True
        return False

    def reset_log_scroll(self) -> None:
        """Reset scroll to show most recent messages."""
        self.log_scroll_offset = 0

    def get_toolbar_slot_at(self, pos: Tuple[int, int], tool_count: int) -> Optional[int]:
        """Get the toolbar slot index at the given position, or None if not over toolbar."""
        if not self.toolbar_rect or not self.toolbar_rect.collidepoint(pos):
            return None
        if self.tool_slot_width <= 0:
            return None

        local_x = pos[0] - self.toolbar_rect.x
        slot = local_x // self.tool_slot_width
        if 0 <= slot < tool_count:
            return slot
        return None

    def get_popup_option_at(self, pos: Tuple[int, int]) -> Optional[int]:
        """Get the popup option index at the given position, or None if not over popup."""
        if not self.popup_rect or not self.popup_rect.collidepoint(pos):
            return None
        if self.popup_option_count <= 0:
            return None

        # Account for 4px padding at top of popup
        local_y = pos[1] - self.popup_rect.y - 4
        if local_y < 0:
            return None

        option_idx = local_y // self.popup_option_height
        if 0 <= option_idx < self.popup_option_count:
            return option_idx
        return None

    def is_over_popup(self, pos: Tuple[int, int]) -> bool:
        """Check if position is over the popup menu."""
        return self.popup_rect is not None and self.popup_rect.collidepoint(pos)

    def clear_popup(self) -> None:
        """Clear popup bounds (called when menu closes)."""
        self.popup_rect = None
        self.popup_option_count = 0

    def _check_target_validity(self, state: "GameState", tool: Optional["Tool"]) -> None:
        """Check if the current target is valid for the selected tool."""
        self.is_valid_target = True  # Default to true
        if tool is None or self.target_cell is None:
            return

        if tool.id.lower() == "build":
            sx, sy = self.target_cell
            # Check bounds
            if not (0 <= sx < GRID_WIDTH and 0 <= sy < GRID_HEIGHT):
                self.is_valid_target = False
                return

            # Check if cell has structure or is rocky terrain
            if self.target_cell in state.structures or state.get_cell_kind(sx, sy) == "rock":
                self.is_valid_target = False

    def update_cursor(
        self,
        virtual_pos: Tuple[int, int],
        camera: "Camera",
        state: "GameState",
        tool: Optional["Tool"],
    ) -> None:
        """Update cursor tracking from mouse position and check target validity.

        Args:
            virtual_pos: Mouse position in virtual screen coordinates
            camera: Camera for coordinate transforms
            state: The main game state for checking validity
            tool: The currently selected tool
        """
        world_sub_width = GRID_WIDTH
        world_sub_height = GRID_HEIGHT
        player_pos = state.player_state.position

        # Check if mouse is over the map viewport
        if not self.map_rect.collidepoint(virtual_pos):
            self.hovered_cell = None
            self.target_cell = None
            self.is_valid_target = False
            return

        # Convert virtual screen position to viewport-local position
        local_x = virtual_pos[0] - self.map_rect.x
        local_y = virtual_pos[1] - self.map_rect.y

        # Scale from UI rect to camera viewport
        scale_x = camera.viewport_width / self.map_rect.width
        scale_y = camera.viewport_height / self.map_rect.height

        viewport_x = local_x * scale_x
        viewport_y = local_y * scale_y

        # Convert viewport position to world position
        world_x, world_y = camera.viewport_to_world(viewport_x, viewport_y)

        # Convert world position to grid coordinates
        self.hovered_cell = camera.world_to_subsquare(world_x, world_y)

        # Clamp to world bounds
        self.hovered_cell = clamp_to_bounds(
            self.hovered_cell, world_sub_width, world_sub_height
        )

        # Clamp to interaction range of player
        self.target_cell = clamp_to_range(
            player_pos, self.hovered_cell, INTERACTION_RANGE
        )

        # Final bounds check on target
        self.target_cell = clamp_to_bounds(
            self.target_cell, world_sub_width, world_sub_height
        )

        # Check if the determined target is valid for the current tool
        self._check_target_validity(state, tool)


# Global UI state instance
_ui_state = UIState()


def get_ui_state() -> UIState:
    """Get the global UI state instance."""
    return _ui_state
