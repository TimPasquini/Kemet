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
from atmosphere import ATMOSPHERE_REGION_SIZE
from ground import SoilLayer, MATERIAL_LIBRARY
from subgrid import get_subsquare_terrain, ensure_terrain_override

if TYPE_CHECKING:
    from main import GameState
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
    state: "GameState",
    seasonal_modifier: float = 1.0,
) -> List[str]:
    """Apply erosion based on accumulated daily pressures using active sets.

    Args:
        state: The main game state.
        seasonal_modifier: Multiplier for erosion rates.

    Returns:
        List of messages about erosion events.
    """
    messages: List[str] = []
    total_water_erosion = 0.0
    total_wind_erosion = 0.0

    # --- Water Erosion ---
    for sub_x, sub_y in list(state.active_water_subsquares):
        tile_x, tile_y = sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE
        local_x, local_y = sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE
        tile = state.tiles[tile_x][tile_y]
        subsquare = tile.subgrid[local_x][local_y]

        if subsquare.water_passage > WATER_EROSION_THRESHOLD:
            terrain = get_subsquare_terrain(subsquare, tile.terrain)
            exposed = terrain.get_exposed_layer()
            if exposed == SoilLayer.BEDROCK:
                continue

            excess_passage = subsquare.water_passage - WATER_EROSION_THRESHOLD
            resistance = EROSION_RESISTANCE.get(exposed, 0.5)
            erosion = excess_passage * WATER_EROSION_RATE * resistance * seasonal_modifier
            if erosion > 0.0001:
                apply_erosion(subsquare, tile, erosion)
                total_water_erosion += erosion

    # --- Wind Erosion ---
    for tile_x, tile_y in list(state.active_wind_tiles):
        tile = state.tiles[tile_x][tile_y]
        for local_x in range(SUBGRID_SIZE):
            for local_y in range(SUBGRID_SIZE):
                subsquare = tile.subgrid[local_x][local_y]
                if subsquare.wind_exposure > WIND_EROSION_THRESHOLD * 10:
                    terrain = get_subsquare_terrain(subsquare, tile.terrain)
                    exposed = terrain.get_exposed_layer()
                    if exposed == SoilLayer.BEDROCK:
                        continue

                    moisture = get_soil_moisture(tile, local_x, local_y)
                    moisture_mod = 1.0 - (moisture * 0.8)
                    if moisture_mod <= 0.1:
                        continue

                    material = terrain.get_exposed_material()
                    mat_mod = WIND_MATERIAL_MODIFIER.get(material, 0.5)
                    resistance = EROSION_RESISTANCE.get(exposed, 0.5)
                    erosion = (
                        subsquare.wind_exposure * moisture_mod *
                        mat_mod * resistance * WIND_EROSION_RATE * 0.01 * seasonal_modifier
                    )
                    if erosion > 0.0001:
                        apply_erosion(subsquare, tile, erosion)
                        total_wind_erosion += erosion

    # Reset all daily accumulators
    reset_daily_accumulators(state.tiles, state.width, state.height)
    state.active_wind_tiles.clear()

    if total_water_erosion > 1.0:
        messages.append("Water shaped the land overnight.")
    if total_wind_erosion > 0.5:
        messages.append("Wind sculpted exposed surfaces.")

    return messages


def apply_erosion(subsquare: "SubSquare", tile: "Tile", amount: float) -> None:
    """Apply erosion to a subsquare's terrain."""
    subsquare.elevation_offset -= amount * 0.01
    if amount > 0.1:
        terrain = ensure_terrain_override(subsquare, tile.terrain)
        layer = terrain.get_exposed_layer()
        if layer != SoilLayer.BEDROCK:
            depth_to_remove = max(1, int(amount))
            terrain.remove_material_from_layer(layer, depth_to_remove)
        subsquare.invalidate_appearance()


def reset_daily_accumulators(tiles: List[List["Tile"]], width: int, height: int) -> None:
    """Reset all daily accumulators without applying erosion."""
    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]
            for row in tile.subgrid:
                for subsquare in row:
                    subsquare.water_passage = 0.0
                    subsquare.wind_exposure = 0.0


def accumulate_wind_exposure(state: "GameState") -> None:
    """Accumulate wind exposure for overnight erosion, using active sets."""
    atmosphere = state.atmosphere
    if not atmosphere:
        return

    state.active_wind_tiles.clear()

    for rx in range(atmosphere.width):
        for ry in range(atmosphere.height):
            region = atmosphere.regions[rx][ry]
            if region.wind_speed < 0.2:
                continue

            start_tx, start_ty = rx * ATMOSPHERE_REGION_SIZE, ry * ATMOSPHERE_REGION_SIZE
            end_tx, end_ty = start_tx + ATMOSPHERE_REGION_SIZE, start_ty + ATMOSPHERE_REGION_SIZE

            for tile_x in range(start_tx, end_tx):
                for tile_y in range(start_ty, end_ty):
                    if not (0 <= tile_x < state.width and 0 <= tile_y < state.height):
                        continue

                    state.active_wind_tiles.add((tile_x, tile_y))
                    tile = state.tiles[tile_x][tile_y]
                    for row in tile.subgrid:
                        for subsquare in row:
                            if subsquare.surface_water < 10:
                                subsquare.wind_exposure += region.wind_speed
