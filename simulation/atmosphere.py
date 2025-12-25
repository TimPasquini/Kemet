# simulation/atmosphere.py
"""
Grid-based atmosphere simulation using NumPy arrays.

Replaces the legacy object-oriented AtmosphereLayer system with vectorized
operations on humidity_grid and wind_grid at full 180×135 resolution.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import numpy as np
from scipy.ndimage import gaussian_filter

if TYPE_CHECKING:
    from main import GameState


# Simulation parameters
HUMIDITY_DRIFT_RATE = 0.01      # Max random drift per tick (±0.01)
WIND_DRIFT_RATE = 0.025         # Max random drift per component per tick
DIFFUSION_SIGMA = 1.5           # Gaussian blur sigma for spatial diffusion
HEAT_HUMIDITY_FACTOR = 1.0 / 1000  # Heat effect on humidity: (heat - 100) / 1000


def simulate_atmosphere_tick_vectorized(state: "GameState") -> None:
    """Update atmosphere grids for one simulation tick (vectorized).

    Performs:
    1. Random humidity drift across entire grid
    2. Heat effect on humidity (reduces humidity when hot)
    3. Wind vector random walk
    4. Spatial diffusion via gaussian_filter
    5. Value clamping to valid ranges

    This function is designed to run every 2 ticks (not every tick) for performance.
    Call from main simulation loop with: if state.turn % 2 == 0: ...
    """
    if state.humidity_grid is None or state.wind_grid is None:
        return

    grid_w, grid_h = state.humidity_grid.shape

    # === 1. Humidity Evolution ===

    # Random drift: uniform random in [-0.01, +0.01]
    humidity_drift = np.random.uniform(-HUMIDITY_DRIFT_RATE, HUMIDITY_DRIFT_RATE,
                                       (grid_w, grid_h)).astype(np.float32)

    # Heat effect: high heat reduces humidity
    # Legacy: heat_factor = (heat - 100) / 1000
    # At heat=140: -0.04, at heat=60: +0.04
    heat_effect = (state.heat - 100) * HEAT_HUMIDITY_FACTOR

    # Apply drift and heat effect
    state.humidity_grid += humidity_drift - heat_effect

    # Spatial diffusion (humidity spreads to neighbors)
    # sigma=1.5 provides gentle smoothing without destroying local variation
    state.humidity_grid = gaussian_filter(state.humidity_grid, sigma=DIFFUSION_SIGMA,
                                          mode='nearest').astype(np.float32)

    # Clamp humidity to valid range [0.1, 0.9]
    # Legacy used same range to prevent extremes
    np.clip(state.humidity_grid, 0.1, 0.9, out=state.humidity_grid)

    # === 2. Wind Evolution ===

    # Random walk for each component independently
    # Each component drifts by ±WIND_DRIFT_RATE
    wind_drift_x = np.random.uniform(-WIND_DRIFT_RATE, WIND_DRIFT_RATE,
                                     (grid_w, grid_h)).astype(np.float32)
    wind_drift_y = np.random.uniform(-WIND_DRIFT_RATE, WIND_DRIFT_RATE,
                                     (grid_w, grid_h)).astype(np.float32)

    state.wind_grid[:, :, 0] += wind_drift_x
    state.wind_grid[:, :, 1] += wind_drift_y

    # Spatial diffusion for wind components (wind patterns spread)
    state.wind_grid[:, :, 0] = gaussian_filter(state.wind_grid[:, :, 0],
                                                sigma=DIFFUSION_SIGMA,
                                                mode='nearest').astype(np.float32)
    state.wind_grid[:, :, 1] = gaussian_filter(state.wind_grid[:, :, 1],
                                                sigma=DIFFUSION_SIGMA,
                                                mode='nearest').astype(np.float32)

    # Clamp wind components to reasonable bounds
    # Legacy wind_speed was 0-1, magnitude = sqrt(x²+y²)
    # So components should be roughly -0.7 to +0.7 to keep magnitude < 1.0
    np.clip(state.wind_grid[:, :, 0], -0.7, 0.7, out=state.wind_grid[:, :, 0])
    np.clip(state.wind_grid[:, :, 1], -0.7, 0.7, out=state.wind_grid[:, :, 1])


def get_wind_magnitude(state: "GameState", sx: int, sy: int) -> float:
    """Get wind speed magnitude at a grid cell.

    Args:
        state: Game state with wind_grid
        sx, sy: Grid cell coordinates

    Returns:
        Wind magnitude (0.0-1.0 range typically)
    """
    if state.wind_grid is None:
        return 0.0

    wind_x = state.wind_grid[sx, sy, 0]
    wind_y = state.wind_grid[sx, sy, 1]
    return float(np.sqrt(wind_x**2 + wind_y**2))


def get_wind_angle(state: "GameState", sx: int, sy: int) -> float:
    """Get wind direction angle at a grid cell.

    Args:
        state: Game state with wind_grid
        sx, sy: Grid cell coordinates

    Returns:
        Angle in radians (0 = east, counter-clockwise)
        Returns 0.0 if wind is negligible
    """
    if state.wind_grid is None:
        return 0.0

    wind_x = state.wind_grid[sx, sy, 0]
    wind_y = state.wind_grid[sx, sy, 1]

    magnitude = np.sqrt(wind_x**2 + wind_y**2)
    if magnitude < 0.01:  # Negligible wind
        return 0.0

    return float(np.arctan2(wind_y, wind_x))
