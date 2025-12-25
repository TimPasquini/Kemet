"""
ground.py - Fixed-layer terrain system for Kemet

Implements a fixed-layer soil horizon model:
- Bedrock (immutable base)
- Regolith (weathered rock fragments)
- Subsoil (mineral accumulation)
- Eluviation (leached transitional layer)
- Topsoil (active mineral soil)
- Organics (living soil layer)

Each layer has an integer depth representing units of material.
Surface elevation is calculated from sum of all layer depths.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Dict
from enum import IntEnum

from config import DEPTH_UNIT_MM, SEA_LEVEL

# Layer names as enum for type safety
class SoilLayer(IntEnum):
    BEDROCK = 0
    REGOLITH = 1
    SUBSOIL = 2
    ELUVIATION = 3
    TOPSOIL = 4
    ORGANICS = 5


@dataclass
class MaterialProperties:
    """Physical properties of earth materials."""
    name: str
    permeability_vertical: int      # 0-100, how fast water seeps down (percentage)
    permeability_horizontal: int    # 0-100, how fast water flows sideways (percentage)
    porosity: int                   # 0-100, max water storage as percentage of volume
    excavatable: bool               # Can player dig/remove this material?
    
    # Visual/gameplay properties
    display_color: Tuple[int, int, int] = (150, 120, 90)
    evap_multiplier: int = 100      # Multiplier for surface evaporation (100 = 1.0x)


# Material library - single source of truth for all material types
MATERIAL_LIBRARY = {
    "bedrock": MaterialProperties(
        name="bedrock",
        permeability_vertical=0,
        permeability_horizontal=0,
        porosity=0,
        excavatable=False,
        display_color=(80, 80, 80),
        evap_multiplier=0,
    ),
    "rock": MaterialProperties(
        name="rock",
        permeability_vertical=5,
        permeability_horizontal=3,
        porosity=10,
        excavatable=False,
        display_color=(120, 120, 110),
        evap_multiplier=90,
    ),
    "gravel": MaterialProperties(
        name="gravel",
        permeability_vertical=90,
        permeability_horizontal=70,
        porosity=25,
        excavatable=True,
        display_color=(160, 160, 150),
        evap_multiplier=130,
    ),
    "sand": MaterialProperties(
        name="sand",
        permeability_vertical=60,
        permeability_horizontal=40,
        porosity=35,
        excavatable=True,
        display_color=(204, 174, 120),
        evap_multiplier=120,
    ),
    "dirt": MaterialProperties(
        name="dirt",
        permeability_vertical=30,
        permeability_horizontal=20,
        porosity=40,
        excavatable=True,
        display_color=(150, 120, 90),
        evap_multiplier=100,
    ),
    "clay": MaterialProperties(
        name="clay",
        permeability_vertical=5,
        permeability_horizontal=2,
        porosity=45,
        excavatable=True,
        display_color=(120, 100, 80),
        evap_multiplier=70,
    ),
    "silt": MaterialProperties(
        name="silt",
        permeability_vertical=20,
        permeability_horizontal=15,
        porosity=42,
        excavatable=True,
        display_color=(180, 175, 170),
        evap_multiplier=85,
    ),
    "humus": MaterialProperties(
        name="humus",
        permeability_vertical=40,
        permeability_horizontal=25,
        porosity=60,
        excavatable=True,
        display_color=(60, 50, 40),
        evap_multiplier=60,
    ),
}


def create_default_terrain(bedrock_base: int, total_soil_depth: int) -> Dict[str, any]:
    """
    Helper to create a simple terrain column with default layer distribution.
    
    Args:
        bedrock_base: Elevation of bedrock bottom (relative to sea level)
        total_soil_depth: Total depth of soil to distribute across layers
    
    Returns:
        Dictionary with terrain properties for a single cell.
    """
    # Default distribution (percentages of total soil depth)
    # These are typical for a generic desert soil profile
    regolith_pct = 30    # 30% weathered rock
    subsoil_pct = 30     # 30% mineral accumulation
    eluviation_pct = 15  # 15% transition
    topsoil_pct = 25     # 25% active soil
    _organics_pct = 0     # 0% organic (desert - starts empty)

    depths = {
        SoilLayer.BEDROCK: 10,
        SoilLayer.REGOLITH: (total_soil_depth * regolith_pct) // 100,
        SoilLayer.SUBSOIL: (total_soil_depth * subsoil_pct) // 100,
        SoilLayer.ELUVIATION: (total_soil_depth * eluviation_pct) // 100,
        SoilLayer.TOPSOIL: (total_soil_depth * topsoil_pct) // 100,
        SoilLayer.ORGANICS: 0,
    }

    materials = {
        SoilLayer.BEDROCK: "bedrock",
        SoilLayer.REGOLITH: "gravel",
        SoilLayer.SUBSOIL: "clay",
        SoilLayer.ELUVIATION: "silt",
        SoilLayer.TOPSOIL: "dirt",
        SoilLayer.ORGANICS: "humus",
    }

    return {
        "bedrock_base": bedrock_base,
        "depths": depths,
        "materials": materials,
    }


def elevation_to_units(meters: float) -> int:
    """Convert floating point meters to integer depth units."""
    return int(meters * 1000 / DEPTH_UNIT_MM)


def units_to_meters(units: int) -> float:
    """Convert integer depth units to floating point meters."""
    return units * DEPTH_UNIT_MM / 1000.0

# =============================================================================
# BIOME TYPES
# =============================================================================
@dataclass
class BiomeType:
    """Simulation properties for a biome type.

    Biome types define how grid cells behave in simulation (evaporation, water
    capacity). Visual rendering is handled separately via surface_state.py
    based on terrain materials and environmental factors.
    """
    name: str
    char: str       # ASCII character for text rendering (debug)
    evap: int       # Base evaporation rate
    capacity: int   # Water holding capacity
    retention: int  # Water retention percentage


BIOME_TYPES: Dict[str, BiomeType] = {
    # Evap rates reduced ~10x for realistic water persistence
    # At heat=100, evap per grid cell per tick: dune=1, flat=1, wadi=0, rock=1, salt=1
    "dune": BiomeType("dune", ".", evap=1, capacity=60, retention=5),
    "flat": BiomeType("flat", ",", evap=1, capacity=90, retention=8),
    "wadi": BiomeType("wadi", "w", evap=0, capacity=140, retention=20),  # Wadis retain water well
    "rock": BiomeType("rock", "^", evap=1, capacity=50, retention=2),
    "salt": BiomeType("salt", "_", evap=2, capacity=70, retention=3),   # Salt flats dry fastest
}
