# render/config.py
"""
Configuration constants for the rendering domain.
Includes UI dimensions, colors, font sizes, and other visual tuning values.
"""
from __future__ import annotations

from typing import Dict, Tuple

# =============================================================================
# UI LAYOUT & DIMENSIONS
# =============================================================================
# Sub-squares are player-scale tiles (48px each)
# Simulation tiles contain 3x3 sub-squares (144px each)
SUB_TILE_SIZE = 48                        # Player-scale tile size in pixels
TILE_SIZE = SUB_TILE_SIZE * 3             # 144px simulation tile (SUBGRID_SIZE is in main config)

VIRTUAL_WIDTH = 1280
VIRTUAL_HEIGHT = 720

SIDEBAR_WIDTH = 300
LINE_HEIGHT = 20
FONT_SIZE = 18
SECTION_SPACING = 8
TOOLBAR_HEIGHT = 32
LOG_PANEL_HEIGHT = 100

# Popup Menu
POPUP_OPTION_HEIGHT = 24
POPUP_WIDTH = 140

# Rendering constants
PLAYER_RADIUS = 18                    # Player circle radius in pixels
STRUCTURE_INSET = 36                  # Inset for structure rendering
TRENCH_INSET = 45                     # Inset for trench rendering
WELLSPRING_RADIUS = 27                # Wellspring indicator radius
PROFILE_WIDTH = 140
PROFILE_HEIGHT = 240
PROFILE_MARGIN = 10
METER_SCALE = 60                      # Pixels per meter for soil profile

# =============================================================================
# COLORS
# =============================================================================
# UI Colors
COLOR_BG_DARK = (20, 20, 25)
COLOR_BG_PANEL = (25, 25, 30)
COLOR_BORDER = (40, 40, 40)
COLOR_BORDER_LIGHT = (80, 80, 85)
COLOR_TEXT_WHITE = (230, 230, 230)
COLOR_TEXT_GRAY = (160, 160, 160)
COLOR_TEXT_DIM = (100, 100, 100)
COLOR_TEXT_HIGHLIGHT = (220, 200, 120)
COLOR_TEXT_SELECTED = (255, 255, 200)

# Toolbar Colors
TOOLBAR_BG_COLOR: Tuple[int, int, int] = (30, 30, 35)
TOOLBAR_SELECTED_COLOR: Tuple[int, int, int] = (60, 55, 40)
TOOLBAR_TEXT_COLOR: Tuple[int, int, int] = (200, 200, 180)

# Map / Feature Colors
COLOR_WATER_DEEP = (48, 133, 214)
COLOR_WATER_SHALLOW = (92, 180, 238)
COLOR_WELLSPRING_STRONG = (100, 180, 240)
COLOR_SKY = (160, 210, 250)
COLOR_WELLSPRING_WEAK = (70, 140, 220)
COLOR_DEPOT = (200, 200, 60)
COLOR_STRUCTURE = (30, 30, 30)
COLOR_TRENCH = (60, 100, 120)
COLOR_PLAYER = (240, 240, 90)
COLOR_PLAYER_ACTION_BG = (50, 50, 50)
COLOR_PLAYER_ACTION_BAR = (200, 200, 80)

# Tool Highlight Colors
HIGHLIGHT_COLORS = {
    "build": (80, 140, 200),      # Blue for building
    "build_invalid": (200, 80, 80),  # Red for invalid placement
    "shovel": (200, 180, 80),     # Yellow for terrain
    "bucket": (80, 180, 200),     # Cyan for water
    "survey": (80, 200, 120),     # Green for survey
    "default": (180, 180, 180),   # White/gray for no tool
}

# Elevation-based coloring
ELEVATION_BRIGHTNESS_MIN = 0.7
ELEVATION_BRIGHTNESS_MAX = 1.3
MATERIAL_BLEND_WEIGHT = 0.35
ORGANICS_BLEND_WEIGHT = 0.50

# Biome base colors
BIOME_COLORS: Dict[str, Tuple[int, int, int]] = {
    "dune": (204, 174, 120),
    "flat": (188, 158, 112),
    "wadi": (150, 125, 96),
    "rock": (128, 128, 128),
    "salt": (220, 220, 210),
}
