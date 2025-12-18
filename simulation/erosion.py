# simulation/erosion.py
"""Overnight erosion processing for Kemet.

Erosion runs during rest/overnight cycles, not every tick.
Uses accumulated daily pressures (water_passage) and current wind state.

Key concepts:
- Water erosion: Based on accumulated water_passage from day's flow
- Wind erosion: Based on current atmosphere wind + terrain exposure
- Sediment deposition: Material accumulates in low-velocity areas
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from config import SUBGRID_SIZE
from ground import SoilLayer, MATERIAL_LIBRARY
from subgrid import get_subsquare_terrain, ensure_terrain_override

if TYPE_CHECKING:
    from mapgen import Tile
    from atmosphere import AtmosphereLayer
    from subgrid import SubSquare

Point = Tuple[int, int]

# =============================================================================
# EROSION CONFIGURATION
# =============================================================================

# Water erosion thresholds (based on accumulated water_passage)
WATER_EROSION_THRESHOLD = 100.0      # Min water passage before erosion occurs
WATER_EROSION_RATE = 0.001           # Erosion per unit of water passage above threshold

# Wind erosion thresholds
WIND_EROSION_THRESHOLD = 0.3         # Min wind speed (0-1) for erosion
WIND_EROSION_RATE = 0.05             # Base erosion rate from wind

# Material resistance (lower = more resistant)
EROSION_RESISTANCE: Dict[SoilLayer, float] = {
    SoilLayer.ORGANICS: 1.0,      # Very erodible
    SoilLayer.TOPSOIL: 0.7,
    SoilLayer.ELUVIATION: 0.8,
    SoilLayer.SUBSOIL: 0.4,
    SoilLayer.REGOLITH: 0.5,
    SoilLayer.BEDROCK: 0.0,       # Cannot erode
}

# Wind-specific material modifiers
WIND_MATERIAL_MODIFIER: Dict[str, float] = {
    "sand": 1.5,      # Very wind-erodible
    "silt": 1.2,
    "humus": 0.8,     # Binds together
    "clay": 0.3,      # Cohesive
    "gravel": 0.2,    # Too heavy
    "dirt": 0.6,
}

# Direction offsets for wind (0=N, clockwise)
DIRECTION_OFFSETS: Dict[int, Tuple[int, int]] = {
    0: (0, -1), 1: (1, -1), 2: (1, 0), 3: (1, 1),
    4: (0, 1), 5: (-1, 1), 6: (-1, 0), 7: (-1, -1),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_subsquare_elevation(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get absolute elevation of a subsquare."""
    base_elev = tile.terrain.get_surface_elevation()
    offset_units = int(tile.subgrid[local_x][local_y].elevation_offset * 10)
    return base_elev + offset_units


def get_wind_exposure(
    sub_x: int, sub_y: int,
    wind_direction: int,
    tiles: List[List["Tile"]],
    sub_width: int, sub_height: int,
) -> float:
    """Calculate wind exposure (0-1) based on upwind terrain."""
    # Get upwind offset (opposite of wind direction)
    dx, dy = DIRECTION_OFFSETS[wind_direction]
    upwind_x, upwind_y = sub_x - dx, sub_y - dy

    # Edge of map = fully exposed
    if not (0 <= upwind_x < sub_width and 0 <= upwind_y < sub_height):
        return 1.0

    # Get elevations
    tile_x, tile_y = sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE
    local_x, local_y = sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE
    my_elev = get_subsquare_elevation(tiles[tile_x][tile_y], local_x, local_y)

    upwind_tile_x, upwind_tile_y = upwind_x // SUBGRID_SIZE, upwind_y // SUBGRID_SIZE
    upwind_local_x, upwind_local_y = upwind_x % SUBGRID_SIZE, upwind_y % SUBGRID_SIZE
    upwind_elev = get_subsquare_elevation(
        tiles[upwind_tile_x][upwind_tile_y], upwind_local_x, upwind_local_y
    )

    # Higher upwind terrain provides shelter
    if upwind_elev > my_elev:
        shelter = min((upwind_elev - my_elev) / 5.0, 0.8)
        return 1.0 - shelter

    return 1.0


def get_soil_moisture(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get moisture level (0-1) affecting wind erosion resistance."""
    subsquare = tile.subgrid[local_x][local_y]

    # Surface water = fully wet
    if subsquare.surface_water > 10:
        return 1.0

    # Check soil saturation
    terrain = get_subsquare_terrain(subsquare, tile.terrain)
    exposed = terrain.get_exposed_layer()
    if exposed == SoilLayer.BEDROCK:
        return 0.0

    max_storage = terrain.get_max_water_storage(exposed)
    if max_storage <= 0:
        return 0.0

    current = tile.water.get_layer_water(exposed)
    saturation = current / max_storage

    # Surface water adds moisture
    surface_factor = min(subsquare.surface_water / 20.0, 0.3)

    return min(1.0, saturation * 0.7 + surface_factor)


# =============================================================================
# MAIN OVERNIGHT PROCESSING
# =============================================================================

def apply_overnight_erosion(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
    atmosphere: Optional["AtmosphereLayer"],
    seasonal_modifier: float = 1.0,
) -> List[str]:
    """Apply erosion based on accumulated daily pressures.

    Called during rest/overnight. Returns messages about significant changes.

    Args:
        tiles: 2D tile array
        width, height: Map dimensions in tiles
        atmosphere: Atmosphere layer for wind data
        seasonal_modifier: Multiplier for erosion rates (rainy season = higher)

    Returns:
        List of messages about erosion events
    """
    messages: List[str] = []
    sub_width = width * SUBGRID_SIZE
    sub_height = height * SUBGRID_SIZE

    total_water_erosion = 0.0
    total_wind_erosion = 0.0

    for sub_x in range(sub_width):
        for sub_y in range(sub_height):
            tile_x = sub_x // SUBGRID_SIZE
            tile_y = sub_y // SUBGRID_SIZE
            local_x = sub_x % SUBGRID_SIZE
            local_y = sub_y % SUBGRID_SIZE

            tile = tiles[tile_x][tile_y]
            subsquare = tile.subgrid[local_x][local_y]

            terrain = get_subsquare_terrain(subsquare, tile.terrain)
            exposed = terrain.get_exposed_layer()

            # Skip bedrock
            if exposed == SoilLayer.BEDROCK:
                subsquare.water_passage = 0.0
                continue

            erosion_amount = 0.0

            # --- Water Erosion ---
            if subsquare.water_passage > WATER_EROSION_THRESHOLD:
                excess_passage = subsquare.water_passage - WATER_EROSION_THRESHOLD
                resistance = EROSION_RESISTANCE.get(exposed, 0.5)
                water_erosion = excess_passage * WATER_EROSION_RATE * resistance * seasonal_modifier
                erosion_amount += water_erosion
                total_water_erosion += water_erosion

            # --- Wind Erosion (using accumulated exposure) ---
            if subsquare.wind_exposure > WIND_EROSION_THRESHOLD * 10:  # Scale threshold for accumulated
                # Check moisture (wet soil resists wind)
                moisture = get_soil_moisture(tile, local_x, local_y)
                moisture_mod = 1.0 - (moisture * 0.8)  # Wet = 80% reduction

                if moisture_mod > 0.1:  # Only if not too wet
                    # Material modifier
                    material = terrain.get_exposed_material()
                    mat_mod = WIND_MATERIAL_MODIFIER.get(material, 0.5)

                    resistance = EROSION_RESISTANCE.get(exposed, 0.5)
                    wind_erosion = (
                        subsquare.wind_exposure * moisture_mod *
                        mat_mod * resistance * WIND_EROSION_RATE * 0.01 * seasonal_modifier
                    )
                    erosion_amount += wind_erosion
                    total_wind_erosion += wind_erosion

            # --- Apply Erosion ---
            if erosion_amount > 0.0001:
                apply_erosion(subsquare, tile, erosion_amount)

            # Reset daily accumulators
            subsquare.water_passage = 0.0
            subsquare.wind_exposure = 0.0

    # Generate summary messages
    if total_water_erosion > 1.0:
        messages.append(f"Water shaped the land overnight.")
    if total_wind_erosion > 0.5:
        messages.append(f"Wind sculpted exposed surfaces.")

    return messages


def apply_erosion(subsquare: "SubSquare", tile: "Tile", amount: float) -> None:
    """Apply erosion to a subsquare's terrain.

    Modifies elevation_offset for micro-terrain changes.
    For significant erosion, also affects layer depths.
    """
    # Modify micro-terrain (elevation_offset in meters)
    subsquare.elevation_offset -= amount * 0.01

    # For significant erosion, remove from layer depth
    if amount > 0.1:
        terrain = ensure_terrain_override(subsquare, tile.terrain)
        layer = terrain.get_exposed_layer()

        if layer != SoilLayer.BEDROCK:
            # Convert to depth units (amount is abstract, scale appropriately)
            depth_to_remove = max(1, int(amount))
            terrain.remove_material_from_layer(layer, depth_to_remove)

        subsquare.invalidate_appearance()


def reset_daily_accumulators(tiles: List[List["Tile"]], width: int, height: int) -> None:
    """Reset all daily accumulators without applying erosion.

    Used when skipping overnight processing (e.g., loading a game).
    """
    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]
            for row in tile.subgrid:
                for subsquare in row:
                    subsquare.water_passage = 0.0
                    subsquare.wind_exposure = 0.0


# =============================================================================
# IMMEDIATE FEEDBACK (LIGHTWEIGHT REAL-TIME)
# =============================================================================

def settle_sediment_in_water(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
) -> None:
    """Settle loose sediment in still/slow water. Called occasionally, not every tick."""
    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]
            for row in tile.subgrid:
                for subsquare in row:
                    if subsquare.sediment_load > 0 and subsquare.surface_water > 5:
                        # Sediment settles in water - deposit it
                        deposit = min(subsquare.sediment_load, 5)
                        subsquare.elevation_offset += deposit * 0.001
                        subsquare.sediment_load -= deposit
                        if subsquare.sediment_load <= 0:
                            subsquare.sediment_material = None


def can_place_material(
    subsquare: "SubSquare",
    tile: "Tile",
    material_type: str,
    atmosphere: Optional["AtmosphereLayer"] = None,
    tile_x: int = 0,
    tile_y: int = 0,
) -> Tuple[bool, str]:
    """Check if player can place material here (immediate feedback).

    Returns (allowed, reason_if_blocked).
    """
    # Can't pile loose material in flowing water
    if material_type in ("organics", "sand", "dirt"):
        if subsquare.surface_water > 20:
            # Check if water is flowing (high water_passage means active flow)
            if subsquare.water_passage > 50:
                return False, "Water washes material away"

    # Can't pile loose/light material on windy days
    if material_type in ("sand", "dirt", "organics"):
        if atmosphere is not None:
            region = atmosphere.get_region_at_tile(tile_x, tile_y)
            # High wind blows away loose material
            if region.wind_speed > 0.6:
                # Organics are lightest
                if material_type == "organics" and region.wind_speed > 0.4:
                    return False, "Wind blows organics away"
                # Sand is wind-erodible
                if material_type == "sand" and region.wind_speed > 0.5:
                    return False, "Wind scatters sand"
                # Dirt needs strong wind
                if material_type == "dirt" and region.wind_speed > 0.7:
                    return False, "Wind blows dirt away"

    return True, ""


def accumulate_wind_exposure(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
    atmosphere: "AtmosphereLayer",
) -> None:
    """Accumulate wind exposure for overnight erosion. Call periodically, not every tick."""
    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]
            region = atmosphere.get_region_at_tile(tile_x, tile_y)

            # Only track significant wind
            if region.wind_speed < 0.2:
                continue

            for row in tile.subgrid:
                for subsquare in row:
                    # Exposed subsquares accumulate wind pressure
                    # Skip if wet (water protects from wind erosion)
                    if subsquare.surface_water < 10:
                        subsquare.wind_exposure += region.wind_speed
