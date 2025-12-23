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

from typing import TYPE_CHECKING, Dict, List, Tuple
import numpy as np

from config import SUBGRID_SIZE
from simulation.config import (
    WATER_EROSION_THRESHOLD,
    WATER_EROSION_RATE,
    WIND_EROSION_THRESHOLD,
    WIND_EROSION_RATE,
)
from atmosphere import ATMOSPHERE_REGION_SIZE
from ground import SoilLayer

if TYPE_CHECKING:
    from main import GameState
    from mapgen import Tile
    from atmosphere import AtmosphereLayer
    from subgrid import SubSquare

Point = Tuple[int, int]

# =============================================================================
# EROSION CONFIGURATION
# =============================================================================

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

def get_grid_elevation(state: "GameState", sx: int, sy: int) -> int:
    """Get absolute elevation of a grid cell in depth units from arrays."""
    return (
        state.bedrock_base[sx, sy] +
        np.sum(state.terrain_layers[:, sx, sy])
    )


def get_wind_exposure(
    state: "GameState",
    sx: int, sy: int,
    wind_direction: int,
) -> float:
    """Calculate wind exposure (0-1) based on upwind terrain."""
    grid_w, grid_h = state.width * SUBGRID_SIZE, state.height * SUBGRID_SIZE
    
    # Get upwind offset (opposite of wind direction)
    dx, dy = DIRECTION_OFFSETS[wind_direction]
    upwind_x, upwind_y = sx - dx, sy - dy

    # Edge of map = fully exposed
    if not (0 <= upwind_x < grid_w and 0 <= upwind_y < grid_h):
        return 1.0

    # Get elevations
    my_elev = get_grid_elevation(state, sx, sy)
    upwind_elev = get_grid_elevation(state, upwind_x, upwind_y)

    # Higher upwind terrain provides shelter
    # 1 unit = 0.1m. A 0.5m difference (5 units) provides full shelter?
    # Original code used 5.0 (meters?) or units? 
    # Original get_subsquare_elevation returned units.
    # So 5 units = 0.5m.
    if upwind_elev > my_elev:
        shelter = min((upwind_elev - my_elev) / 5.0, 0.8)
        return 1.0 - shelter

    return 1.0


def get_soil_moisture(state: "GameState", sx: int, sy: int) -> float:
    """Get moisture level (0-1) affecting wind erosion resistance."""
    surface_water = state.water_grid[sx, sy]

    # Surface water = fully wet
    if surface_water > 10:
        return 1.0

    # Check soil saturation
    # Find exposed layer
    exposed = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed = layer
            break
            
    if exposed is None: # Bedrock
        return 0.0

    depth = state.terrain_layers[exposed, sx, sy]
    porosity = state.porosity_grid[exposed, sx, sy]
    max_storage = (depth * porosity) // 100
    
    if max_storage <= 0:
        return 0.0

    current = state.subsurface_water_grid[exposed, sx, sy]
    saturation = current / max_storage

    # Surface water adds moisture
    surface_factor = min(surface_water / 20.0, 0.3)

    return min(1.0, saturation * 0.7 + surface_factor)


def get_exposed_layer_and_material(state: "GameState", sx: int, sy: int) -> Tuple[SoilLayer, str]:
    """Get the topmost non-empty soil layer and its material name."""
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            return layer, state.terrain_materials[layer, sx, sy]
    return SoilLayer.BEDROCK, "bedrock"


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
    for sx, sy in list(state.active_water_subsquares):
        water_passage = state.water_passage_grid[sx, sy]

        if water_passage > WATER_EROSION_THRESHOLD:
            exposed, _ = get_exposed_layer_and_material(state, sx, sy)

            if exposed == SoilLayer.BEDROCK:
                continue

            excess_passage = water_passage - WATER_EROSION_THRESHOLD
            resistance = EROSION_RESISTANCE.get(exposed, 0.5)
            erosion = excess_passage * WATER_EROSION_RATE * resistance * seasonal_modifier
            if erosion > 0.0001:
                apply_erosion(state, sx, sy, erosion)
                total_water_erosion += erosion

    # --- Wind Erosion ---
    for tile_x, tile_y in list(state.active_wind_tiles):
        for local_x in range(SUBGRID_SIZE):
            for local_y in range(SUBGRID_SIZE):
                sx, sy = tile_x * SUBGRID_SIZE + local_x, tile_y * SUBGRID_SIZE + local_y
                wind_exposure = state.wind_exposure_grid[sx, sy]

                if wind_exposure > WIND_EROSION_THRESHOLD * 10:
                    exposed, material = get_exposed_layer_and_material(state, sx, sy)

                    if exposed == SoilLayer.BEDROCK:
                        continue

                    moisture = get_soil_moisture(state, sx, sy)
                    moisture_mod = 1.0 - (moisture * 0.8)
                    if moisture_mod <= 0.1:
                        continue

                    mat_mod = WIND_MATERIAL_MODIFIER.get(material, 0.5)
                    resistance = EROSION_RESISTANCE.get(exposed, 0.5)
                    erosion = (
                        wind_exposure * moisture_mod *
                        mat_mod * resistance * WIND_EROSION_RATE * 0.01 * seasonal_modifier
                    )
                    if erosion > 0.0001:
                        apply_erosion(state, sx, sy, erosion)
                        total_wind_erosion += erosion

    # Reset all daily accumulators
    reset_daily_accumulators(state)
    state.active_wind_tiles.clear()

    if total_water_erosion > 1.0:
        messages.append("Water shaped the land overnight.")
    if total_wind_erosion > 0.5:
        messages.append("Wind sculpted exposed surfaces.")

    return messages


def apply_erosion(state: "GameState", sx: int, sy: int, amount: float) -> None:
    """Apply erosion to a grid cell's terrain (Arrays)."""
    # Material Removal: remove actual soil from terrain layers
    if amount > 0:
        layer, _ = get_exposed_layer_and_material(state, sx, sy)
        if layer != SoilLayer.BEDROCK:
            depth_to_remove = max(1, int(amount))
            current_depth = state.terrain_layers[layer, sx, sy]
            actual_remove = min(current_depth, depth_to_remove)
            state.terrain_layers[layer, sx, sy] -= actual_remove
            
            # If layer depleted, clear material name
            if state.terrain_layers[layer, sx, sy] == 0:
                state.terrain_materials[layer, sx, sy] = ""
            
            state.terrain_changed = True
            state.dirty_subsquares.add((sx, sy))


def reset_daily_accumulators(state: "GameState") -> None:
    """Reset all daily accumulators without applying erosion."""
    state.water_passage_grid.fill(0.0)
    state.wind_exposure_grid.fill(0.0)


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
                    for local_x in range(SUBGRID_SIZE):
                        for local_y in range(SUBGRID_SIZE):
                            sx, sy = tile_x * SUBGRID_SIZE + local_x, tile_y * SUBGRID_SIZE + local_y
                            if state.water_grid[sx, sy] < 10:
                                state.wind_exposure_grid[sx, sy] += region.wind_speed
