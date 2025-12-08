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
from typing import Tuple, Optional
from enum import IntEnum

# Reference elevation (sea level equivalent)
SEA_LEVEL = 0

# Layer depth units (1 unit = ~10cm for granularity while staying integer)
# This gives us millimeter precision when we need it: 1 unit = 100mm
DEPTH_UNIT_MM = 100

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
        display_color=(140, 110, 85),
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


@dataclass
class TerrainColumn:
    """
    Fixed-layer soil horizon model for a single tile.
    
    Each layer has:
    - material: what it's made of
    - depth: how much material (integer units, 1 unit = 100mm)
    
    Surface elevation is calculated from sum of depths relative to sea level.
    """
    # Fixed layer structure (always 6 layers)
    bedrock_depth: int          # Immutable base layer
    regolith_material: str      # Weathered rock
    regolith_depth: int
    subsoil_material: str       # Mineral accumulation
    subsoil_depth: int
    eluviation_material: str    # Leached transition
    eluviation_depth: int
    topsoil_material: str       # Active mineral soil
    topsoil_depth: int
    organics_material: str      # Living soil
    organics_depth: int
    
    # Reference elevation of bedrock base
    bedrock_base: int           # Elevation of bottom of bedrock (relative to sea level)
    
    def get_layer_material(self, layer: SoilLayer) -> str:
        """Get the material type for a specific layer."""
        if layer == SoilLayer.BEDROCK:
            return "bedrock"
        elif layer == SoilLayer.REGOLITH:
            return self.regolith_material
        elif layer == SoilLayer.SUBSOIL:
            return self.subsoil_material
        elif layer == SoilLayer.ELUVIATION:
            return self.eluviation_material
        elif layer == SoilLayer.TOPSOIL:
            return self.topsoil_material
        elif layer == SoilLayer.ORGANICS:
            return self.organics_material
        return "bedrock"
    
    def get_layer_depth(self, layer: SoilLayer) -> int:
        """Get the depth (in units) for a specific layer."""
        if layer == SoilLayer.BEDROCK:
            return self.bedrock_depth
        elif layer == SoilLayer.REGOLITH:
            return self.regolith_depth
        elif layer == SoilLayer.SUBSOIL:
            return self.subsoil_depth
        elif layer == SoilLayer.ELUVIATION:
            return self.eluviation_depth
        elif layer == SoilLayer.TOPSOIL:
            return self.topsoil_depth
        elif layer == SoilLayer.ORGANICS:
            return self.organics_depth
        return 0
    
    def set_layer_depth(self, layer: SoilLayer, depth: int) -> None:
        """Set the depth for a specific layer."""
        depth = max(0, depth)  # Can't have negative depth
        
        if layer == SoilLayer.REGOLITH:
            self.regolith_depth = depth
        elif layer == SoilLayer.SUBSOIL:
            self.subsoil_depth = depth
        elif layer == SoilLayer.ELUVIATION:
            self.eluviation_depth = depth
        elif layer == SoilLayer.TOPSOIL:
            self.topsoil_depth = depth
        elif layer == SoilLayer.ORGANICS:
            self.organics_depth = depth
        # Bedrock depth is immutable
    
    def get_layer_elevation_range(self, layer: SoilLayer) -> Tuple[int, int]:
        """
        Get the bottom and top elevation for a specific layer.
        
        Returns (bottom_elevation, top_elevation) relative to sea level.
        """
        bottom = self.bedrock_base
        
        # Add up layers below the target
        for i in range(layer + 1):
            if i < layer:
                bottom += self.get_layer_depth(SoilLayer(i))
        
        top = bottom + self.get_layer_depth(layer)
        return bottom, top
    
    def get_surface_elevation(self) -> int:
        """Calculate surface elevation from sum of all layer depths."""
        return (self.bedrock_base + 
                self.bedrock_depth + 
                self.regolith_depth + 
                self.subsoil_depth + 
                self.eluviation_depth + 
                self.topsoil_depth + 
                self.organics_depth)
    
    def get_layer_at_elevation(self, elevation: int) -> Optional[SoilLayer]:
        """Find which layer contains the given elevation."""
        current = self.bedrock_base
        
        for layer in SoilLayer:
            depth = self.get_layer_depth(layer)
            if elevation >= current and elevation < current + depth:
                return layer
            current += depth
        
        return None  # Above surface
    
    def get_total_soil_depth(self) -> int:
        """Get total depth of all soil layers (excluding bedrock)."""
        return (self.regolith_depth + 
                self.subsoil_depth + 
                self.eluviation_depth + 
                self.topsoil_depth + 
                self.organics_depth)
    
    def add_material_to_layer(self, layer: SoilLayer, amount: int) -> None:
        """Add material to a layer (increases depth)."""
        if layer == SoilLayer.BEDROCK:
            return  # Can't modify bedrock
        
        current = self.get_layer_depth(layer)
        self.set_layer_depth(layer, current + amount)
    
    def remove_material_from_layer(self, layer: SoilLayer, amount: int) -> int:
        """
        Remove material from a layer (decreases depth).
        
        Returns the actual amount removed (may be less if layer is thinner).
        """
        if layer == SoilLayer.BEDROCK:
            return 0  # Can't modify bedrock
        
        current = self.get_layer_depth(layer)
        actual_removed = min(amount, current)
        self.set_layer_depth(layer, current - actual_removed)
        return actual_removed
    
    def get_max_water_storage(self, layer: SoilLayer) -> int:
        """
        Calculate maximum water storage for a layer.
        
        Returns water capacity in same units as depth.
        """
        material = self.get_layer_material(layer)
        props = MATERIAL_LIBRARY.get(material)
        if not props:
            return 0
        
        depth = self.get_layer_depth(layer)
        # porosity is percentage (0-100), depth is in units
        return (depth * props.porosity) // 100


@dataclass
class SurfaceTraits:
    """
    Surface characteristics for a tile.
    
    Placeholder for future implementation of:
    - Ground cover (grass, mulch, bare)
    - Growing plants (crops, wild plants)
    - Surface structures (buildings, equipment)
    - Surface water features (puddles, ice)
    """
    # For now, just track basic state
    has_trench: bool = False
    has_structure: bool = False  # Will link to structure system
    
    # Future additions:
    # ground_cover: Optional[str] = None
    # growing_plants: List[Plant] = field(default_factory=list)
    # surface_structures: List[Structure] = field(default_factory=list)


def create_default_terrain(bedrock_base: int, total_soil_depth: int) -> TerrainColumn:
    """
    Helper to create a simple terrain column with default layer distribution.
    
    Args:
        bedrock_base: Elevation of bedrock bottom (relative to sea level)
        total_soil_depth: Total depth of soil to distribute across layers
    
    Returns:
        TerrainColumn with reasonable layer distribution
    """
    # Default distribution (percentages of total soil depth)
    # These are typical for a generic desert soil profile
    regolith_pct = 30    # 30% weathered rock
    subsoil_pct = 30     # 30% mineral accumulation
    eluviation_pct = 15  # 15% transition
    topsoil_pct = 25     # 25% active soil
    organics_pct = 0     # 0% organic (desert - starts empty)
    
    return TerrainColumn(
        bedrock_depth=10,  # Fixed bedrock thickness (1m)
        regolith_material="gravel",
        regolith_depth=(total_soil_depth * regolith_pct) // 100,
        subsoil_material="sand",
        subsoil_depth=(total_soil_depth * subsoil_pct) // 100,
        eluviation_material="silt",
        eluviation_depth=(total_soil_depth * eluviation_pct) // 100,
        topsoil_material="dirt",
        topsoil_depth=(total_soil_depth * topsoil_pct) // 100,
        organics_material="humus",
        organics_depth=0,  # Start empty - player builds this
        bedrock_base=bedrock_base,
    )


def elevation_to_units(meters: float) -> int:
    """Convert floating point meters to integer depth units."""
    return int(meters * 1000 / DEPTH_UNIT_MM)


def units_to_meters(units: int) -> float:
    """Convert integer depth units to floating point meters."""
    return units * DEPTH_UNIT_MM / 1000.0
