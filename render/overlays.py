# render/overlays.py
"""Overlay rendering: help screen, night effect, event log."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import pygame

from render.primitives import draw_text
from render.config import (
    LINE_HEIGHT,
    COLOR_BG_PANEL,
    COLOR_TEXT_HIGHLIGHT,
    COLOR_TEXT_GRAY,
    COLOR_TEXT_DIM,
)

if TYPE_CHECKING:
    from main import GameState
    from camera import Camera


def render_help_overlay(
    surface,
    font,
    controls: List[str],
    pos: Tuple[int, int],
    available_width: int,
    available_height: int,
) -> None:
    """Render the help overlay with control descriptions.

    Args:
        surface: The pygame surface to draw on.
        font: The pygame font to use for rendering text.
        controls: A list of strings, each describing a control.
        pos: The (x, y) coordinates for the top-left corner of the overlay.
        available_width: The maximum width for the overlay.
        available_height: The maximum height for the overlay.
    """
    x, y = pos
    col_width, row_height = 130, 18
    cols = max(1, available_width // col_width)

    pygame.draw.rect(surface, COLOR_BG_PANEL, (x - 4, y - 4, available_width, available_height), 0)
    draw_text(surface, font, "CONTROLS", (x, y), color=COLOR_TEXT_HIGHLIGHT)
    y += row_height + 4

    for i, control in enumerate(controls):
        cx = x + (i % cols * col_width)
        cy = y + (i // cols * row_height)
        if cy + row_height < pos[1] + available_height:
            draw_text(surface, font, control, (cx, cy), color=COLOR_TEXT_GRAY)


def render_event_log(
    surface,
    font,
    state: "GameState",
    pos: Tuple[int, int],
    max_height: int,
    scroll_offset: int = 0,
) -> int:
    """Render the event log messages with scroll support.

    This is optimized to avoid converting the message deque to a list every frame.

    Args:
        surface: The pygame surface to draw on.
        font: The pygame font to use for rendering text.
        state: The current game state, containing the message log.
        pos: The (x, y) coordinates for the top-left corner of the log.
        max_height: The maximum height for the event log area.
        scroll_offset: Number of messages scrolled up from bottom (0 = most recent visible).

    Returns:
        Number of visible message slots (for scroll calculations).
    """
    log_x, log_y = pos
    messages = state.messages  # messages is a deque
    total_messages = len(messages)

    # Header with scroll indicator
    header = "EVENT LOG"
    if scroll_offset > 0:
        header += f" [{scroll_offset}^]"
    draw_text(surface, font, header, (log_x, log_y), color=COLOR_TEXT_HIGHLIGHT)
    log_y += LINE_HEIGHT + 4

    # Calculate visible messages
    visible_count = (max_height - 40) // 18
    if visible_count <= 0:
        return 0

    # Calculate index range with scroll offset
    end_idx = total_messages - scroll_offset
    start_idx = max(0, end_idx - visible_count)
    end_idx = max(start_idx, end_idx)  # Ensure end >= start

    # Iterate directly over the deque using indices to avoid creating a list
    for i in range(start_idx, end_idx):
        msg = messages[i]
        draw_text(surface, font, f"• {msg}", (log_x, log_y), color=(160, 200, 160))
        log_y += 18

    # Show scroll hint if there are more messages
    if scroll_offset > 0 or start_idx > 0:
        hint_parts = []
        if start_idx > 0:
            hint_parts.append(f"{start_idx} older")
        if scroll_offset > 0:
            hint_parts.append(f"{scroll_offset} newer")
        hint = f"[scroll: {', '.join(hint_parts)}]"
        draw_text(surface, font, hint, (log_x, log_y), color=COLOR_TEXT_DIM)

    return visible_count


def render_night_overlay(
    surface: pygame.Surface,
    heat: int,
) -> None:
    """Render the night darkness overlay based on heat level.

    Args:
        surface: Surface to render overlay to
        heat: Current heat value (lower = darker night)
    """
    # Calculate alpha: more alpha (more opaque) when heat is low
    night_alpha = max(0, min(200, int((140 - heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        surface.blit(overlay, (0, 0))
