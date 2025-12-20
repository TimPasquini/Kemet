# config.py
"""
Centralized game configuration for Kemet.

This file contains high-level, cross-cutting constants.
Domain-specific constants are in:
- simulation/config.py (physics, erosion, etc.)
- render/config.py (colors, UI dimensions, etc.)
"""
from __future__ import annotations

from typing import Dict, Tuple

# =============================================================================
# CORE GAME DESIGN
# =============================================================================
SUBGRID_SIZE = 3              # 3x3 sub-squares per tile. The ONE constant to rule them all.
INTERACTION_RANGE = 2         # Sub-squares player can reach (1-2 squares out)
MAP_SIZE: Tuple[int, int] = (60, 45)  # Large world for exploration

# =============================================================================
# UNITS & SCALE
# =============================================================================
# ELEVATION MODEL:
# - All elevation/depth values stored in "depth units"
# - 1 depth unit = 100mm = 0.1 meters
# - SEA_LEVEL (0) is the reference point
# - Typical bedrock_base: -25 to -20 units (2.0-2.5m below sea level)
#
# SUBSQUARE MICRO-TERRAIN:
# - SubSquare.elevation_offset is stored in METERS (not depth units)
# - Convert to depth units: offset_units = int(elevation_offset * 10)
# - Typical range: -0.05 to +0.05 meters (-0.5 to +0.5 depth units)
#
# ELEVATION HIERARCHY:
# - Tile surface elevation = bedrock_base + sum(all layer depths)
# - Subsquare elevation = tile surface + offset_units
# - Water surface height = subsquare elevation + surface_water amount

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
MOISTURE_EMA_ALPHA = 0.05  # Exponential moving average factor for moisture tracking

# =============================================================================
# WATER CONSERVATION
# =============================================================================
INITIAL_WATER_POOL = 100000    # Starting water in global pool (10,000L)
MIN_GAMEPLAY_WATER = 10000     # Minimum water to ensure at game start

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
MOVE_SPEED = 220
DIAGONAL_FACTOR = 0.707

# Starting Inventory
STARTING_WATER = 200        # 20.0L
STARTING_SCRAP = 6
STARTING_SEEDS = 2
STARTING_BIOMASS = 0

# =============================================================================
# DEPOT / RESUPPLY
# =============================================================================
DEPOT_WATER_AMOUNT = 300    # Units (30L)
DEPOT_SCRAP_AMOUNT = 3
DEPOT_SEEDS_AMOUNT = 1

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
