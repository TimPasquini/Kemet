# render/__init__.py
"""
Rendering module for Kemet pygame frontend.

Provides modular rendering functions for map, HUD, toolbar, and overlays.
"""
from render.colors import (
    Color,
    calculate_elevation_range,
    elevation_brightness,
    apply_brightness,
    blend_colors,
    get_surface_material_color,
    color_for_tile,
)
from render.primitives import draw_text, draw_section_header
from render.map import render_map, render_player
from render.hud import render_hud, render_inventory, render_soil_profile
from render.toolbar import render_toolbar
from render.overlays import render_help_overlay, render_night_overlay, render_event_log

__all__ = [
    # Colors
    "Color",
    "calculate_elevation_range",
    "elevation_brightness",
    "apply_brightness",
    "blend_colors",
    "get_surface_material_color",
    "color_for_tile",
    # Primitives
    "draw_text",
    "draw_section_header",
    # Map
    "render_map",
    "render_player",
    # HUD
    "render_hud",
    "render_inventory",
    "render_soil_profile",
    # Toolbar
    "render_toolbar",
    # Overlays
    "render_help_overlay",
    "render_night_overlay",
    "render_event_log",
]
