# render/primitives.py
"""Basic drawing primitives shared across render modules."""
from __future__ import annotations

from typing import Tuple, Dict

import pygame

from render.config import (
    LINE_HEIGHT,
    COLOR_TEXT_WHITE,
    COLOR_TEXT_HIGHLIGHT,
)

Color = Tuple[int, int, int]

# Text rendering cache to avoid per-frame surface creation for the same text.
# The key is a tuple of (font_id, text, color), and the value is the rendered Surface.
_TEXT_CACHE: Dict[Tuple[int, str, Color], pygame.Surface] = {}


def draw_text(surface, font, text: str, pos: Tuple[int, int], color: Color = COLOR_TEXT_WHITE) -> None:
    """Draw text at the given position, using a cache to avoid re-rendering."""
    # Use the font object's id as part of the key to handle multiple fonts.
    font_id = id(font)
    cache_key = (font_id, text, color)

    # Check if the rendered text surface is already in the cache.
    if cache_key not in _TEXT_CACHE:
        # If not, render the text and store the new surface in the cache.
        _TEXT_CACHE[cache_key] = font.render(text, True, color)

    # Blit the cached surface.
    surface.blit(_TEXT_CACHE[cache_key], pos)


def draw_section_header(surface, font, text: str, pos: Tuple[int, int], width: int = 200) -> int:
    """Draw a section header with underline. Returns the y position after the header."""
    x, y = pos
    draw_text(surface, font, text, (x, y), color=COLOR_TEXT_HIGHLIGHT)
    y += LINE_HEIGHT
    pygame.draw.line(surface, (100, 100, 80), (x, y), (x + width, y), 1)
    return y + 6
