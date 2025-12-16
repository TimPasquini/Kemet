"""Surface state computation for visual rendering.

This module computes the visual appearance of sub-squares from environmental
factors. The "appearance" represents what the player sees - determined by:

Current factors:
- Exposed material (from terrain column)
- Surface water presence

Future factors (to be added):
- Water type (fresh, brackish, stagnant)
- Organics volume
- Humidity/moisture history
- Player structures
- Neighboring tile states

The appearance drives:
- Base color selection
- Future: texture patterns, layered rendering
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Tuple, Optional, Set

from ground import MATERIAL_LIBRARY, SoilLayer

if TYPE_CHECKING:
    from subgrid import SubSquare
    from mapgen import Tile

Color = Tuple[int, int, int]


# =============================================================================
# Appearance Types
# =============================================================================

# Base appearance types derived from materials
# These replace the old biome strings but are computed, not stored
APPEARANCE_TYPES = {
    # Material-based appearances
    "bedrock": {"base_color": (80, 80, 80), "pattern": None},
    "rock": {"base_color": (120, 120, 110), "pattern": None},
    "gravel": {"base_color": (160, 160, 150), "pattern": "speckled"},
    "sand": {"base_color": (204, 174, 120), "pattern": "drifts"},
    "dirt": {"base_color": (150, 120, 90), "pattern": None},
    "clay": {"base_color": (120, 100, 80), "pattern": None},
    "silt": {"base_color": (140, 110, 85), "pattern": None},
    "humus": {"base_color": (60, 50, 40), "pattern": None},

    # State-modified appearances (future expansion)
    "wet_sand": {"base_color": (180, 150, 100), "pattern": "drifts"},
    "muddy": {"base_color": (100, 80, 60), "pattern": None},
    "flooded": {"base_color": (80, 120, 160), "pattern": "ripples"},
    "vegetated": {"base_color": (80, 120, 60), "pattern": "grass"},
}

# Fallback for unknown types
DEFAULT_APPEARANCE = {"base_color": (150, 120, 90), "pattern": None}


@dataclass
class SurfaceAppearance:
    """Computed visual state of a sub-square.

    This is computed from environmental factors, not stored.
    """
    appearance_type: str          # Key into APPEARANCE_TYPES
    base_color: Color             # RGB color for rendering
    pattern: Optional[str]        # Future: texture pattern hint
    water_tint: float = 0.0       # 0-1, amount of water color blending
    features: Set[str] = field(default_factory=set) # Renderable features like 'trench'
    brightness_mod: float = 1.0   # Multiplier for elevation-based lighting

    @property
    def display_color(self) -> Color:
        """Get the final color for rendering (before elevation brightness)."""
        if self.water_tint > 0:
            # Blend with water blue
            water_color = (60, 120, 180)
            r = int(self.base_color[0] * (1 - self.water_tint) + water_color[0] * self.water_tint)
            g = int(self.base_color[1] * (1 - self.water_tint) + water_color[1] * self.water_tint)
            b = int(self.base_color[2] * (1 - self.water_tint) + water_color[2] * self.water_tint)
            return (r, g, b)
        return self.base_color


# =============================================================================
# Appearance Computation
# =============================================================================

def compute_surface_appearance(
    subsquare: "SubSquare",
    tile: "Tile",
) -> SurfaceAppearance:
    """Compute the visual appearance of a sub-square from environmental factors.

    Args:
        subsquare: The sub-square to compute appearance for
        tile: Parent tile (for terrain data if no override)

    Returns:
        SurfaceAppearance with computed visual state
    """
    from subgrid import get_subsquare_terrain

    # Get effective terrain (sub-square override or tile terrain)
    terrain = get_subsquare_terrain(subsquare, tile.terrain)

    # Determine base appearance from exposed material
    exposed_layer = terrain.get_exposed_layer()
    material_name = terrain.get_layer_material(exposed_layer)

    # Get appearance properties
    appearance_data = APPEARANCE_TYPES.get(material_name, DEFAULT_APPEARANCE)
    base_color = appearance_data["base_color"]
    pattern = appearance_data.get("pattern")
    appearance_type = material_name

    # --- Populate features set ---
    features = set()
    if subsquare.has_trench:
        features.add("trench")

    # Modify based on surface water
    water_tint = 0.0
    if subsquare.surface_water > 0:
        # Light tint for small amounts, stronger for more water
        if subsquare.surface_water > 50:
            water_tint = 0.4
            appearance_type = "flooded"
        elif subsquare.surface_water > 20:
            water_tint = 0.25
        elif subsquare.surface_water > 5:
            water_tint = 0.1

    # Future: modify based on organics layer depth
    if terrain.organics_depth > 0:
        # Blend toward humus color based on organics depth
        organics_factor = min(terrain.organics_depth / 10.0, 1.0)  # Max at 1m depth
        humus_color = MATERIAL_LIBRARY["humus"].display_color
        r = int(base_color[0] * (1 - organics_factor * 0.6) + humus_color[0] * organics_factor * 0.6)
        g = int(base_color[1] * (1 - organics_factor * 0.6) + humus_color[1] * organics_factor * 0.6)
        b = int(base_color[2] * (1 - organics_factor * 0.6) + humus_color[2] * organics_factor * 0.6)
        base_color = (r, g, b)
        if organics_factor > 0.3:
            appearance_type = "vegetated" if organics_factor > 0.6 else material_name

    # Future hooks for additional factors:
    # - Humidity state (from atmosphere layer)
    # - Neighboring tile influence
    # - Structure presence
    # - Water type (if different water types are added)

    return SurfaceAppearance(
        appearance_type=appearance_type,
        base_color=base_color,
        pattern=pattern,
        features=features,
        water_tint=water_tint,
    )


def get_appearance_color(
    subsquare: "SubSquare",
    tile: "Tile",
) -> Color:
    """Convenience function to get just the display color for a sub-square.

    Use this in rendering when you only need the color, not full appearance data.
    """
    appearance = compute_surface_appearance(subsquare, tile)
    return appearance.display_color


# =============================================================================
# Legacy Compatibility
# =============================================================================

# Map old biome names to closest material/appearance type
# Used during transition from stored biome to computed appearance
LEGACY_BIOME_MAP = {
    "dune": "sand",
    "flat": "dirt",
    "wadi": "silt",
    "rock": "rock",
    "salt": "sand",  # Salt flats are sandy with mineral deposits
}


def biome_to_appearance_type(biome: str) -> str:
    """Convert legacy biome name to appearance type.

    Used during transition period for backwards compatibility.
    """
    return LEGACY_BIOME_MAP.get(biome, "dirt")


# =============================================================================
# Unified Water Access
# =============================================================================

def get_subsquare_total_water(subsquare: "SubSquare", tile: "Tile") -> int:
    """Get total water associated with a sub-square.

    Combines surface water (per sub-square) with a proportional share of
    the tile's subsurface water.

    Args:
        subsquare: The sub-square to query
        tile: Parent tile (for subsurface water)

    Returns:
        Total water amount in units (surface + subsurface share)
    """
    # Surface water is stored per sub-square
    surface = subsquare.surface_water

    # Subsurface water is shared across the tile (9 sub-squares)
    # Each sub-square gets 1/9 of the subsurface water
    subsurface = tile.water.total_subsurface_water() // 9

    return surface + subsurface


def get_subsquare_surface_water(subsquare: "SubSquare") -> int:
    """Get surface water for a sub-square.

    Simple accessor for consistency with unified water access pattern.
    """
    return subsquare.surface_water


def get_tile_total_water(tile: "Tile") -> int:
    """Get total water for a tile (all sub-squares + subsurface).

    Args:
        tile: The tile to query

    Returns:
        Total water in units (all surface + all subsurface)
    """
    surface = sum(ss.surface_water for row in tile.subgrid for ss in row)
    subsurface = tile.water.total_subsurface_water()
    return surface + subsurface
