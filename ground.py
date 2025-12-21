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
from typing import Tuple, Optional, Dict
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

        if layer == SoilLayer.BEDROCK:
            self.bedrock_depth = depth
        elif layer == SoilLayer.REGOLITH:
            self.regolith_depth = depth
        elif layer == SoilLayer.SUBSOIL:
            self.subsoil_depth = depth
        elif layer == SoilLayer.ELUVIATION:
            self.eluviation_depth = depth
        elif layer == SoilLayer.TOPSOIL:
            self.topsoil_depth = depth
        elif layer == SoilLayer.ORGANICS:
            self.organics_depth = depth
    
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
            if current <= elevation < current + depth:
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
        current = self.get_layer_depth(layer)
        self.set_layer_depth(layer, current + amount)
    
    def remove_material_from_layer(self, layer: SoilLayer, amount: int) -> int:
        """
        Remove material from a layer (decreases depth).
        
        Returns the actual amount removed (could be less if layer is thinner).
        """
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

    def get_exposed_layer(self) -> SoilLayer:
        """Get the topmost layer with non-zero depth.

        Returns the layer that would be visible/accessible at the surface.
        This is what the shovel operates on, what erosion affects, etc.
        """
        for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                      SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
            if self.get_layer_depth(layer) > 0:
                return layer
        return SoilLayer.BEDROCK

    def get_exposed_material(self) -> str:
        """Get the material type of the exposed (topmost) layer."""
        return self.get_layer_material(self.get_exposed_layer())


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
    has_structure: bool = False  # Will link to structure system
    
    # Future additions:
    # ground_cover: Optional[str] = None
    # growing_plants: List[Plant] = field(default_factory=list)
    # surface_structures: List[Structure] = field(default_factory=list)


def layers_can_connect(
    src_terrain: TerrainColumn,
    src_layer: SoilLayer,
    dst_terrain: TerrainColumn,
    dst_layer: SoilLayer
) -> bool:
    """Check if two layers have overlapping elevation ranges for horizontal flow.

    For water to flow horizontally between two tiles at a given layer,
    the layer elevation ranges must overlap. A bedrock ridge higher than
    a neighbor's regolith top would block flow at that layer.

    Args:
        src_terrain: Source tile's terrain column
        src_layer: Layer in source tile
        dst_terrain: Destination tile's terrain column
        dst_layer: Layer in destination tile

    Returns:
        True if layers can exchange water horizontally
    """
    src_bot, src_top = src_terrain.get_layer_elevation_range(src_layer)
    dst_bot, dst_top = dst_terrain.get_layer_elevation_range(dst_layer)

    # Ranges overlap if: src_bottom < dst_top AND dst_bottom < src_top
    return src_bot < dst_top and dst_bot < src_top


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
    _organics_pct = 0     # 0% organic (desert - starts empty)
    
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

# =============================================================================
# TILE TYPES (BIOMES)
# =============================================================================
@dataclass
class TileType:
    """Simulation properties for a tile type.

    Tile types define how tiles behave in simulation (evaporation, water
    capacity). Visual rendering is handled separately via surface_state.py
    based on terrain materials and environmental factors.
    """
    name: str
    char: str       # ASCII character for text rendering (debug)
    evap: int       # Base evaporation rate
    capacity: int   # Water holding capacity
    retention: int  # Water retention percentage


TILE_TYPES: Dict[str, TileType] = {
    # Evap rates reduced ~10x for realistic water persistence
    # At heat=100, evap per sub-square per tick: dune=1, flat=1, wadi=0, rock=1, salt=1
    "dune": TileType("dune", ".", evap=1, capacity=60, retention=5),
    "flat": TileType("flat", ",", evap=1, capacity=90, retention=8),
    "wadi": TileType("wadi", "w", evap=0, capacity=140, retention=20),  # Wadis retain water well
    "rock": TileType("rock", "^", evap=1, capacity=50, retention=2),
    "salt": TileType("salt", "_", evap=2, capacity=70, retention=3),   # Salt flats dry fastest
}
