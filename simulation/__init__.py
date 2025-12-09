# simulation/__init__.py
"""Simulation modules for Kemet.

- surface: Sub-grid surface water flow (high frequency)
- subsurface: Tile-level underground water (lower frequency)
"""

from simulation.surface import simulate_surface_flow
from simulation.subsurface import simulate_subsurface_tick

__all__ = ["simulate_surface_flow", "simulate_subsurface_tick"]
