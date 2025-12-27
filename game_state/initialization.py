# game_state/initialization.py
"""Game state initialization and world generation."""
from __future__ import annotations

import numpy as np

from core.config import (
        GRID_WIDTH,
    GRID_HEIGHT,
    INITIAL_WATER_POOL,
)
from game_state.state import GameState
from world.terrain import (
    SoilLayer,
    MATERIAL_LIBRARY,
    create_default_terrain,
    elevation_to_units,
)
from world.generation import generate_grids_direct
from interface.player import PlayerState
from structures import Depot
from world_state import GlobalWaterPool
from simulation.subsurface_cache import SubsurfaceConnectivityCache


def build_initial_state() -> GameState:
    """Create a new game state with generated map.

    Uses the unified 180×135 grid for all spatial data.
    """
    # Generate all grid data directly
    grids = generate_grids_direct(GRID_WIDTH, GRID_HEIGHT)

    # Extract grids from returned dict
    terrain_layers = grids["terrain_layers"]
    terrain_materials = grids["terrain_materials"]
    subsurface_water_grid = grids["subsurface_water_grid"]
    bedrock_base = grids["bedrock_base"]
    wellspring_grid = grids["wellspring_grid"]
    water_grid = grids["water_grid"]
    kind_grid = grids["kind_grid"]

    # Calculate material property grids from terrain_materials (VECTORIZED)
    permeability_vert_grid = np.zeros((len(SoilLayer), GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)
    permeability_horiz_grid = np.zeros((len(SoilLayer), GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)
    porosity_grid = np.zeros((len(SoilLayer), GRID_WIDTH, GRID_HEIGHT), dtype=np.int32)

    # Vectorized approach: process each layer independently, using masks for each material type
    for layer in SoilLayer:
        # For each unique material in this layer, create a mask and assign properties
        for mat_name, mat_props in MATERIAL_LIBRARY.items():
            # Create a boolean mask where this material appears in this layer
            mask = (terrain_materials[layer] == mat_name)

            # Apply properties to all cells with this material at once (vectorized)
            permeability_vert_grid[layer][mask] = mat_props.permeability_vertical
            permeability_horiz_grid[layer][mask] = mat_props.permeability_horizontal
            porosity_grid[layer][mask] = mat_props.porosity

    # Starting position at center of grid
    start_cell = (GRID_WIDTH // 2, GRID_HEIGHT // 2)

    # Update grids for depot location - create good starting terrain in 3x3 area around start
    depot_terrain_props = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            sx = start_cell[0] + dx
            sy = start_cell[1] + dy
            if 0 <= sx < GRID_WIDTH and 0 <= sy < GRID_HEIGHT:
                kind_grid[sx, sy] = "flat"
                wellspring_grid[sx, sy] = 0
                bedrock_base[sx, sy] = depot_terrain_props["bedrock_base"]
                for layer in SoilLayer:
                    terrain_layers[layer, sx, sy] = depot_terrain_props["depths"][layer]
                    terrain_materials[layer, sx, sy] = depot_terrain_props["materials"][layer]

    # Initialize player at starting cell
    player_state = PlayerState()
    player_state.position = start_cell

    # Initialize global water pool
    water_pool = GlobalWaterPool(total_volume=INITIAL_WATER_POOL)

    # Initialize moisture grid at grid resolution
    moisture_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)

    # Initialize trench grid
    trench_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.uint8)

    # Initialize atmosphere grids at full grid resolution
    # Humidity: random initial values similar to legacy system (0.4-0.6)
    humidity_grid = np.random.uniform(0.4, 0.6, (GRID_WIDTH, GRID_HEIGHT)).astype(np.float32)

    # Wind: Convert legacy random direction/speed to 2D vectors
    # Legacy: direction 0-7 (8 directions), speed 0-0.3
    # New: Generate random angles and speeds, convert to (x, y) components
    wind_angles = np.random.uniform(0, 2 * np.pi, (GRID_WIDTH, GRID_HEIGHT))
    wind_speeds = np.random.uniform(0.0, 0.3, (GRID_WIDTH, GRID_HEIGHT))
    wind_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT, 2), dtype=np.float32)
    wind_grid[:, :, 0] = wind_speeds * np.cos(wind_angles)  # x component
    wind_grid[:, :, 1] = wind_speeds * np.sin(wind_angles)  # y component

    # Temperature: uniform 1.0 (inactive for now, but ready for future)
    temperature_grid = np.ones((GRID_WIDTH, GRID_HEIGHT), dtype=np.float32)

    # Initialize daily accumulator grids for erosion
    water_passage_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)
    wind_exposure_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)

    # Pre-allocate random buffer for surface flow (performance optimization)
    random_buffer = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=np.float64)

    # Initialize subsurface connectivity cache (terrain-dependent optimization)
    # rebuild_frequency=None means only rebuild when explicitly invalidated
    subsurface_cache = SubsurfaceConnectivityCache(rebuild_frequency_ticks=None)

    # Initialize elevation_grid (calculated from other grids)
    elevation_grid = bedrock_base + np.sum(terrain_layers, axis=0)

    # Create game state
    state = GameState(
        player_state=player_state,
        water_grid=water_grid,
        elevation_grid=elevation_grid,
        water_pool=water_pool,
        moisture_grid=moisture_grid,
        trench_grid=trench_grid,
        kind_grid=kind_grid,
        water_passage_grid=water_passage_grid,
        wind_exposure_grid=wind_exposure_grid,
        terrain_layers=terrain_layers,
        subsurface_water_grid=subsurface_water_grid,
        bedrock_base=bedrock_base,
        terrain_materials=terrain_materials,
        permeability_vert_grid=permeability_vert_grid,
        permeability_horiz_grid=permeability_horiz_grid,
        porosity_grid=porosity_grid,
        wellspring_grid=wellspring_grid,
        humidity_grid=humidity_grid,
        wind_grid=wind_grid,
        temperature_grid=temperature_grid,
        _random_buffer=random_buffer,
        subsurface_cache=subsurface_cache,
    )

    # Create depot structure at starting cell
    state.structures[start_cell] = Depot()

    return state
