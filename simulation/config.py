# simulation/config.py
"""
Configuration constants for the simulation domain.
Includes physics, erosion, and other simulation-specific tuning values.
"""
from __future__ import annotations

# =============================================================================
# WATER PHYSICS
# =============================================================================
# Flow rates (as percentages: 0-100)
SURFACE_FLOW_RATE = 50       # Fast surface flow (50% per tick)
SURFACE_SEEPAGE_RATE = 15    # Surface water seeping into soil (15% per tick)
SUBSURFACE_FLOW_RATE = 8     # Slow subsurface flow (8% per tick)
OVERFLOW_FLOW_RATE = 90      # Overflow is rapid, high-pressure
VERTICAL_SEEPAGE_RATE = 30   # Vertical seepage speed (30% per tick)
CAPILLARY_RISE_RATE = 5      # Capillary rise is much slower (5% per tick)

# Flow thresholds (in depth units)
SURFACE_FLOW_THRESHOLD = 1     # Min elevation diff for surface flow (~1cm)
SUBSURFACE_FLOW_THRESHOLD = 1  # Min pressure diff for subsurface flow

# =============================================================================
# EROSION & SEDIMENT
# =============================================================================
# Water erosion
WATER_EROSION_THRESHOLD = 100.0      # Min water passage before erosion occurs
WATER_EROSION_RATE = 0.001           # Erosion per unit of water passage above threshold

# Wind erosion
WIND_EROSION_THRESHOLD = 0.3         # Min wind speed (0-1) for erosion
WIND_EROSION_RATE = 0.05             # Base erosion rate from wind

# =============================================================================
# BIOME SIMULATION
# =============================================================================
MOISTURE_HISTORY_MAX = 24   # Ticks of moisture history to track for biome calculation
