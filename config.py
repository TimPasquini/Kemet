# config.py
"""
Centralized game configuration for Kemet.

All magic numbers and constants in one place for easy tuning.
"""
from __future__ import annotations

from typing import Dict, Tuple

# =============================================================================
# UNITS & SCALE
# =============================================================================
DEPTH_UNIT_MM = 100  # 1 depth unit = 100mm (10cm)
SEA_LEVEL = 0        # Reference elevation

# =============================================================================
# TIME & SIMULATION
# =============================================================================
TICK_INTERVAL = 0.25  # Seconds per simulation tick
DAY_LENGTH = 1200     # Ticks per day (5 minutes at 0.25s/tick)

# =============================================================================
# WEATHER & ENVIRONMENT
# =============================================================================
HEAT_MIN = 60
HEAT_MAX = 140
HEAT_NIGHT_THRESHOLD = 90

# Rain timing (in ticks)
RAIN_INTERVAL_MIN = 1200   # Min time between rain events
RAIN_INTERVAL_MAX = 2000   # Max time between rain events
RAIN_DURATION_MIN = 300    # Min rain duration
RAIN_DURATION_MAX = 500    # Max rain duration
RAIN_WELLSPRING_MULTIPLIER = 150  # Percentage boost to wellsprings during rain

# =============================================================================
# WATER PHYSICS
# =============================================================================
# Flow rates (as percentages: 0-100)
SURFACE_FLOW_RATE = 50       # Fast surface flow (50% per tick)
SUBSURFACE_FLOW_RATE = 8     # Slow subsurface flow (8% per tick)
OVERFLOW_FLOW_RATE = 90      # Overflow is rapid, high-pressure
VERTICAL_SEEPAGE_RATE = 30   # Vertical seepage speed (30% per tick)
CAPILLARY_RISE_RATE = 5      # Capillary rise is much slower (5% per tick)

# Flow thresholds (in depth units)
SURFACE_FLOW_THRESHOLD = 1     # Min elevation diff for surface flow (~1cm)
SUBSURFACE_FLOW_THRESHOLD = 1  # Min pressure diff for subsurface flow

# =============================================================================
# STRUCTURES
# =============================================================================
# Cistern
CISTERN_CAPACITY = 500         # Units (50L)
CISTERN_TRANSFER_RATE = 40     # Units per tick
CISTERN_LOSS_RATE = 3          # Units per tick at max heat
CISTERN_LOSS_RECOVERY = 50     # Percentage returned to surface

# Condenser
CONDENSER_OUTPUT = 2           # Units of water per tick (0.2L)

# Planter
PLANTER_GROWTH_RATE = 1        # Growth points per tick
PLANTER_GROWTH_THRESHOLD = 100 # Ticks to mature
PLANTER_WATER_COST = 3         # Units consumed on harvest
PLANTER_WATER_REQUIREMENT = 80 # Units (8L) needed for growth
MAX_ORGANICS_DEPTH = 10        # Cap organic layer at 1m

# Evaporation reduction multipliers (percentage - lower = more reduction)
TRENCH_EVAP_REDUCTION = 85     # 85% = 15% reduction
CISTERN_EVAP_REDUCTION = 40    # 40% = 60% reduction

# Structure costs
STRUCTURE_COSTS: Dict[str, Dict[str, int]] = {
    "cistern": {"scrap": 3},
    "condenser": {"scrap": 2},
    "planter": {"scrap": 1, "seeds": 1},
}

# =============================================================================
# PLAYER & INPUT
# =============================================================================
MAX_POUR_AMOUNT = 1000      # Max pour amount in units (100L)
MIN_LAYER_THICKNESS = 1     # Min thickness when digging
MOISTURE_HISTORY_MAX = 24   # Ticks of moisture history to track

# =============================================================================
# DEPOT / RESUPPLY
# =============================================================================
DEPOT_WATER_AMOUNT = 300    # Units (30L)
DEPOT_SCRAP_AMOUNT = 3
DEPOT_SEEDS_AMOUNT = 1

# =============================================================================
# SUB-GRID SYSTEM
# =============================================================================
SUBGRID_SIZE = 3              # 3x3 sub-squares per tile
INTERACTION_RANGE = 2         # Sub-squares player can reach (1-2 squares out)

# =============================================================================
# UI (Pygame)
# =============================================================================
# Sub-squares are player-scale tiles (48px each)
# Simulation tiles contain 3x3 sub-squares (144px each)
SUB_TILE_SIZE = 48                        # Player-scale tile size in pixels
TILE_SIZE = SUB_TILE_SIZE * SUBGRID_SIZE  # 144px simulation tile

SIDEBAR_WIDTH = 300
LINE_HEIGHT = 20
FONT_SIZE = 18
SECTION_SPACING = 8
MOVE_SPEED = 220
DIAGONAL_FACTOR = 0.707
MAP_SIZE: Tuple[int, int] = (60, 45)  # Large world for exploration

# Rendering constants
PLAYER_RADIUS = 18                    # Player circle radius in pixels
STRUCTURE_INSET = 36                  # Inset for structure rendering
TRENCH_INSET = 45                     # Inset for trench rendering
WELLSPRING_RADIUS = 27                # Wellspring indicator radius
PROFILE_WIDTH = 140
PROFILE_HEIGHT = 240
PROFILE_MARGIN = 10
TOOLBAR_HEIGHT = 32

# Colors
TOOLBAR_BG_COLOR: Tuple[int, int, int] = (30, 30, 35)
TOOLBAR_SELECTED_COLOR: Tuple[int, int, int] = (60, 55, 40)
TOOLBAR_TEXT_COLOR: Tuple[int, int, int] = (200, 200, 180)

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

# =============================================================================
# ACTION DURATIONS (seconds)
# =============================================================================
# Defines how long the player is locked while performing an action
ACTION_DURATIONS: Dict[str, float] = {
    "terrain": 1.0,   # Shovel tool (trench/lower/raise)
    "dig": 1.0,
    "lower": 1.5,
    "raise": 0.8,
    "build": 2.0,
    "collect": 0.5,
    "pour": 0.5,
    "survey": 0.3,
}
