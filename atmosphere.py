# atmosphere.py
"""
DEPRECATED - TO BE REMOVED IN PHASE 3 (Atmosphere Migration)

Legacy object-oriented atmosphere system using coarse regions.

PROBLEMS:
- Coarse Resolution: 4×4 tile regions (12×12 grid cells share identical values)
- Object-Oriented: List[List[AtmosphereRegion]] instead of NumPy arrays
- Iterative Logic: Python for-loops instead of vectorization
- Performance Bottleneck: Blocks scale-up to larger maps

REPLACEMENT: Grid-based atmosphere with humidity_grid and wind_grid at full
grid resolution (180×135), fully vectorized NumPy operations.

This entire file will be deleted after Phase 3 migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple
import random


# Region size in tiles
ATMOSPHERE_REGION_SIZE = 4


@dataclass
class AtmosphereRegion:
    """A region of atmosphere covering 4x4 tiles."""

    humidity: float = 0.5       # 0-1, affects evaporation (higher = less evap)
    wind_direction: int = 0     # 0-7 (8 directions, 0=N, clockwise)
    wind_speed: float = 0.0     # 0-1, affects evaporation and future erosion
    temperature: float = 1.0    # Multiplier for evaporation rates


@dataclass
class AtmosphereLayer:
    """Grid of atmosphere regions covering the map."""

    regions: List[List[AtmosphereRegion]] = field(default_factory=list)
    width: int = 0   # In regions (map_width // ATMOSPHERE_REGION_SIZE)
    height: int = 0  # In regions

    @classmethod
    def create(cls, map_width: int, map_height: int) -> "AtmosphereLayer":
        """Create atmosphere layer for a map of given tile dimensions."""
        width = (map_width + ATMOSPHERE_REGION_SIZE - 1) // ATMOSPHERE_REGION_SIZE
        height = (map_height + ATMOSPHERE_REGION_SIZE - 1) // ATMOSPHERE_REGION_SIZE

        regions = []
        for x in range(width):
            col = []
            for y in range(height):
                # Initialize with slight random variation
                region = AtmosphereRegion(
                    humidity=0.4 + random.random() * 0.2,  # 0.4-0.6
                    wind_direction=random.randint(0, 7),
                    wind_speed=random.random() * 0.3,      # 0-0.3
                    temperature=1.0,
                )
                col.append(region)
            regions.append(col)

        return cls(regions=regions, width=width, height=height)

    def get_region_at_tile(self, tile_x: int, tile_y: int) -> AtmosphereRegion:
        """Get the atmosphere region containing a tile."""
        region_x = tile_x // ATMOSPHERE_REGION_SIZE
        region_y = tile_y // ATMOSPHERE_REGION_SIZE

        # Clamp to valid range
        region_x = max(0, min(region_x, self.width - 1))
        region_y = max(0, min(region_y, self.height - 1))

        return self.regions[region_x][region_y]

    def get_humidity_at_tile(self, tile_x: int, tile_y: int) -> float:
        """Get humidity value affecting a tile (0-1)."""
        return self.get_region_at_tile(tile_x, tile_y).humidity

    def get_evaporation_modifier(self, tile_x: int, tile_y: int) -> float:
        """Get evaporation rate modifier for a tile.

        Returns a multiplier (0.5-1.5) where:
        - High humidity (1.0) -> low evap (0.5x)
        - Low humidity (0.0) -> high evap (1.5x)
        - Wind increases evaporation
        """
        region = self.get_region_at_tile(tile_x, tile_y)

        # Base modifier from humidity (inverted: high humidity = low evap)
        humidity_mod = 1.5 - region.humidity  # 0.5 to 1.5

        # Wind increases evaporation
        wind_mod = 1.0 + region.wind_speed * 0.3  # 1.0 to 1.3

        return humidity_mod * wind_mod


def simulate_atmosphere_tick(atmosphere: AtmosphereLayer, heat: int) -> None:
    """Update atmosphere for one simulation tick.

    Humidity and wind evolve slowly over time:
    - Humidity drifts toward regional average
    - Wind direction occasionally shifts
    - Higher heat reduces humidity
    """
    # Atmosphere changes slowly - only update occasionally
    # For now, small random drift each tick
    for x in range(atmosphere.width):
        for y in range(atmosphere.height):
            region = atmosphere.regions[x][y]

            # Humidity drifts slightly
            drift = (random.random() - 0.5) * 0.02  # -0.01 to +0.01

            # Heat reduces humidity
            heat_factor = (heat - 100) / 1000  # At heat 140, -0.04; at heat 60, +0.04

            region.humidity = max(0.1, min(0.9, region.humidity + drift - heat_factor))

            # Wind occasionally shifts
            if random.random() < 0.01:  # 1% chance per tick
                region.wind_direction = (region.wind_direction + random.choice([-1, 1])) % 8

            # Wind speed drifts
            region.wind_speed = max(0.0, min(1.0, region.wind_speed + (random.random() - 0.5) * 0.05))
