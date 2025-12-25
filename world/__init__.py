# world/__init__.py
"""
World module: terrain, biomes, weather, and world generation.

Provides:
- Terrain and soil layer definitions (from terrain.py)
- Biome calculation and recalculation (from biomes.py)
- Weather system (from weather.py)
- Map generation (from generation.py)
"""

# Core terrain types and utilities
from world.terrain import (
    SoilLayer,
    BiomeType,
    BIOME_TYPES,
    MATERIAL_LIBRARY,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)

# Biome system
from world.biomes import (
    calculate_biome,
    calculate_elevation_percentiles,
    recalculate_biomes,
)

# Weather system
from world.weather import WeatherSystem

# Map generation
from world.generation import generate_grids_direct

__all__ = [
    # Terrain
    "SoilLayer",
    "BiomeType",
    "BIOME_TYPES",
    "MATERIAL_LIBRARY",
    "create_default_terrain",
    "elevation_to_units",
    "units_to_meters",
    # Biomes
    "calculate_biome",
    "calculate_elevation_percentiles",
    "recalculate_biomes",
    # Weather
    "WeatherSystem",
    # Generation
    "generate_grids_direct",
]
