# render/toolbar.py
"""Toolbar and tool options popup rendering."""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, Optional

import pygame

from render.primitives import draw_text
from render.config import (
    TOOLBAR_BG_COLOR,
    TOOLBAR_SELECTED_COLOR,
    TOOLBAR_TEXT_COLOR,
    POPUP_OPTION_HEIGHT,
    POPUP_WIDTH,
    COLOR_TEXT_SELECTED,
    COLOR_TEXT_HIGHLIGHT,
    COLOR_TEXT_GRAY,
    COLOR_TEXT_DIM,
)

if TYPE_CHECKING:
    from interface.tools import Toolbar
    from interface.ui_state import UIState


def _render_tool_options_popup(
    surface,
    font,
    toolbar: "Toolbar",
    tool_x: int,
    toolbar_y: int,
    tool_width: int,
    ui_state: Optional["UIState"] = None,
) -> None:
    """Draw the expanded vertical options menu above the selected tool."""
    tool = toolbar.get_selected_tool()
    if not tool or not tool.options:
        return

    option_height = POPUP_OPTION_HEIGHT
    popup_width = POPUP_WIDTH
    popup_height = len(tool.options) * option_height + 8
    popup_x = tool_x + (tool_width - popup_width) // 2
    popup_y = toolbar_y - popup_height - 4

    # Store popup bounds for mouse interaction
    if ui_state is not None:
        ui_state.popup_rect = pygame.Rect(popup_x, popup_y, popup_width, popup_height)
        ui_state.popup_option_height = option_height
        ui_state.popup_option_count = len(tool.options)

    # Draw popup background
    pygame.draw.rect(surface, (35, 35, 40), (popup_x, popup_y, popup_width, popup_height), border_radius=4)
    pygame.draw.rect(surface, (80, 80, 90), (popup_x, popup_y, popup_width, popup_height), 1, border_radius=4)

    # Draw options
    for i, opt in enumerate(tool.options):
        opt_y = popup_y + 4 + (i * option_height)
        is_highlighted = (i == toolbar.menu_highlight_index)
        is_current = (i == tool.selected_option)

        # Highlight background for selected option
        if is_highlighted:
            pygame.draw.rect(surface, (60, 80, 100), (popup_x + 2, opt_y, popup_width - 4, option_height - 2), border_radius=2)

        # Draw option name
        text_color = COLOR_TEXT_SELECTED if is_highlighted else ((200, 200, 160) if is_current else COLOR_TEXT_GRAY)
        draw_text(surface, font, opt.name, (popup_x + 8, opt_y + 4), color=text_color)

        # Draw checkmark for currently selected option
        if is_current:
            draw_text(surface, font, "*", (popup_x + popup_width - 16, opt_y + 4), color=COLOR_TEXT_HIGHLIGHT)

    # Draw hint at bottom
    hint_y = popup_y + popup_height + 2
    draw_text(surface, font, "W/S:move R:select", (popup_x, hint_y), color=COLOR_TEXT_DIM)


def render_toolbar(
    surface,
    font,
    toolbar: "Toolbar",
    pos: Tuple[int, int],
    width: int,
    height: int,
    ui_state: Optional["UIState"] = None,
) -> None:
    """Render the toolbar with tool slots."""
    x, y = pos
    tools = toolbar.tools
    tool_count = len(tools)
    tool_width = width // tool_count

    # Clear popup bounds if menu is closed
    if ui_state is not None and not toolbar.menu_open:
        ui_state.clear_popup()

    # Draw toolbar background
    pygame.draw.rect(surface, TOOLBAR_BG_COLOR, (x, y, width, height))
    pygame.draw.line(surface, (60, 60, 60), (x, y), (x + width, y), 1)

    selected_tool_x = None

    for i, tool in enumerate(tools):
        tx = x + (i * tool_width)
        is_selected = (i == toolbar.selected_index)

        # Highlight selected tool
        if is_selected:
            pygame.draw.rect(surface, TOOLBAR_SELECTED_COLOR, (tx + 1, y + 1, tool_width - 2, height - 2))
            selected_tool_x = tx

        # Draw tool number and icon
        draw_text(surface, font, f"{i + 1}", (tx + 4, y + 2), color=(150, 150, 130))
        draw_text(surface, font, tool.icon, (tx + 18, y + 2), color=TOOLBAR_TEXT_COLOR)

        # Show current option for tools with menus, or tool name
        if tool.has_menu() and is_selected:
            opt = tool.get_current_option()
            label = opt.name[:6] if opt else tool.name[:6]
            draw_text(surface, font, label, (tx + 4, y + 16), color=(180, 180, 140))
        else:
            draw_text(surface, font, tool.name[:6], (tx + 4, y + 16), color=(140, 140, 140))

        # Separator between tools
        if i < tool_count - 1:
            pygame.draw.line(surface, (50, 50, 50), (tx + tool_width - 1, y + 4), (tx + tool_width - 1, y + height - 4), 1)

    # Draw expanded menu popup if open
    if toolbar.menu_open and selected_tool_x is not None:
        _render_tool_options_popup(surface, font, toolbar, selected_tool_x, y, tool_width, ui_state)
