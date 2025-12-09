# render/primitives.py
"""Basic drawing primitives shared across render modules."""
from __future__ import annotations

from typing import Tuple

import pygame

from config import LINE_HEIGHT

Color = Tuple[int, int, int]


def draw_text(surface, font, text: str, pos: Tuple[int, int], color: Color = (230, 230, 230)) -> None:
    """Draw text at the given position."""
    surface.blit(font.render(text, True, color), pos)


def draw_section_header(surface, font, text: str, pos: Tuple[int, int], width: int = 200) -> int:
    """Draw a section header with underline. Returns the y position after the header."""
    x, y = pos
    draw_text(surface, font, text, (x, y), color=(220, 200, 120))
    y += LINE_HEIGHT
    pygame.draw.line(surface, (100, 100, 80), (x, y), (x + width, y), 1)
    return y + 6
