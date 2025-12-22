# simulation/__init__.py
"""Simulation modules for Kemet.

- surface: Sub-grid surface water flow (high frequency)
- subsurface_vectorized: Vectorized array-based underground water physics
"""

from simulation.surface import simulate_surface_flow
from simulation.subsurface_vectorized import simulate_subsurface_tick_vectorized

__all__ = ["simulate_surface_flow", "simulate_subsurface_tick_vectorized"]
