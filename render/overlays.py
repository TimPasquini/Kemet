# render/overlays.py
"""Overlay rendering: help screen, night effect, event log."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import pygame

from render.primitives import draw_text
from config import LINE_HEIGHT

if TYPE_CHECKING:
    from main import GameState


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

    pygame.draw.rect(surface, (25, 25, 30), (x - 4, y - 4, available_width, available_height), 0)
    draw_text(surface, font, "CONTROLS", (x, y), color=(220, 200, 120))
    y += row_height + 4

    for i, control in enumerate(controls):
        cx = x + (i % cols * col_width)
        cy = y + (i // cols * row_height)
        if cy + row_height < pos[1] + available_height:
            draw_text(surface, font, control, (cx, cy), color=(180, 180, 160))


def render_night_overlay(
    surface,
    state: "GameState",
    map_width: int,
    map_height: int,
) -> None:
    """Render the night darkness overlay based on heat level.

    Args:
        surface: The pygame surface to draw on.
        state: The current game state, containing the heat level.
        map_width: The width of the map area to cover.
        map_height: The height of the map area to cover.
    """
    night_alpha = max(0, min(200, int((140 - state.heat) * 180 // 80)))
    if night_alpha > 0:
        overlay = pygame.Surface((map_width, map_height), pygame.SRCALPHA)
        overlay.fill((10, 20, 40, night_alpha))
        surface.blit(overlay, (0, 0))


def render_event_log(
    surface,
    font,
    state: "GameState",
    pos: Tuple[int, int],
    max_height: int,
    scroll_offset: int = 0,
) -> int:
    """Render the event log messages with scroll support.

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
    total_messages = len(state.messages)

    # Header with scroll indicator
    header = "EVENT LOG"
    if scroll_offset > 0:
        header += f" [{scroll_offset}^]"
    draw_text(surface, font, header, (log_x, log_y), color=(200, 180, 120))
    log_y += LINE_HEIGHT + 4

    # Calculate visible messages
    visible_count = (max_height - 40) // 18
    if visible_count <= 0:
        return 0

    # Calculate slice range with scroll offset
    end_idx = total_messages - scroll_offset
    start_idx = max(0, end_idx - visible_count)
    end_idx = max(start_idx, end_idx)  # Ensure end >= start

    messages_to_show = state.messages[start_idx:end_idx]

    for msg in messages_to_show:
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
        draw_text(surface, font, hint, (log_x, log_y), color=(100, 100, 100))

    return visible_count
