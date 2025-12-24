# mapgen.py
"""
Map generation, tiles, and biome system for Kemet.

Handles:
- Tile and TileType definitions
- Procedural map generation (WFC-style)
- Wellspring placement
- Biome calculation and recalculation
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Tuple, TYPE_CHECKING

import numpy as np
from scipy import ndimage
from ground import (
    TerrainColumn,
    SurfaceTraits,
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
    TileType,
    TILE_TYPES,
)
from utils import get_neighbors

if TYPE_CHECKING:
    from main import GameState
from config import SUBGRID_SIZE
from subgrid import SubSquare
from simulation.surface import distribute_water_to_tile

Point = Tuple[int, int]


# =============================================================================
# Tile Class
# =============================================================================

def _create_default_subgrid() -> List[List[SubSquare]]:
    """Create a 3x3 subgrid."""
    subgrid = []
    for sx in range(SUBGRID_SIZE):
        row = []
        for sy in range(SUBGRID_SIZE):
            row.append(SubSquare())
        subgrid.append(row)
    return subgrid


@dataclass
class Tile:
    """
    A single map tile containing terrain, water, and surface information.

    Each tile contains a 3x3 subgrid for fine-grained surface interactions.
    The subgrid allows water to flow at higher resolution and enables
    buildings to span partial tiles.

    The `kind` field determines simulation properties (evaporation rate,
    water capacity) via TILE_TYPES lookup. Visual rendering is computed
    from terrain materials and environmental state via surface_state.py.
    """
    kind: str                           # Tile type for simulation (evap, capacity, etc.)
    terrain: TerrainColumn              # Soil layers and elevation
    water: WaterColumn                  # Water storage
    surface: SurfaceTraits              # Surface features (trench, etc.)
    wellspring_output: int = 0          # Water output per tick (0 = not a wellspring)
    subgrid: List[List[SubSquare]] = field(default_factory=_create_default_subgrid)

    @property
    def elevation(self) -> float:
        """Surface elevation in meters."""
        return units_to_meters(self.terrain.get_surface_elevation())

    @property
    def hydration(self) -> float:
        """Total water in liters (surface + subsurface)."""
        # Note: This property is broken without grid access. 
        # Should be replaced by get_tile_total_water(tile, grid, x, y)
        return self.water.total_subsurface_water() / 10.0 # Partial fallback

    def get_subsquare(self, local_x: int, local_y: int) -> SubSquare:
        """Get a subsquare by local index (0-2, 0-2)."""
        return self.subgrid[local_x][local_y]


# =============================================================================
# Biome Calculation
# =============================================================================

def calculate_biome(
    state: "GameState",
    tile_x: int,
    tile_y: int,
    neighbor_positions: List[Point],
    elevation_percentile: float,
    avg_moisture: float
) -> str:
    """
    Determine the biome type for a tile based on its properties.

    Args:
        state: GameState with terrain grids
        tile_x: Tile x coordinate
        tile_y: Tile y coordinate
        neighbor_positions: List of (x, y) tuples for adjacent tiles
        elevation_percentile: 0.0-1.0 ranking of elevation (0=lowest, 1=highest)
        avg_moisture: Average moisture level for this tile

    Returns:
        Biome key string (e.g., "dune", "wadi", "rock")
    """
    from ground import SoilLayer

    # Get center subsquare for this tile
    center_sx = tile_x * 3 + 1
    center_sy = tile_y * 3 + 1

    # Calculate soil depth from terrain layers
    soil_depth = (
        state.terrain_layers[SoilLayer.TOPSOIL, center_sx, center_sy] +
        state.terrain_layers[SoilLayer.SUBSOIL, center_sx, center_sy]
    )

    topsoil_material = state.terrain_materials[SoilLayer.TOPSOIL, center_sx, center_sy]
    organics_depth = state.terrain_layers[SoilLayer.ORGANICS, center_sx, center_sy]

    # High elevation with thin soil -> rock
    if elevation_percentile > 0.75 and soil_depth < 5:
        return "rock"

    # Low elevation with moisture -> wadi
    if elevation_percentile < 0.25 and avg_moisture > 50:
        return "wadi"

    # Sandy and dry -> dune
    if topsoil_material == "sand" and avg_moisture < 20:
        return "dune"

    # Low elevation, dry, no organics -> salt flat
    if elevation_percentile < 0.4 and avg_moisture < 15 and organics_depth == 0:
        return "salt"

    # Follow neighbors if strong consensus
    if neighbor_positions:
        neighbor_biomes = [state.get_tile_kind(nx, ny) for nx, ny in neighbor_positions]
        biome_counts = Counter(neighbor_biomes)
        most_common_list = biome_counts.most_common(1)
        if most_common_list:
            most_common, count = most_common_list[0]
            if count >= 3 and most_common in ("dune", "flat", "wadi"):
                return most_common

    return "flat"


def calculate_elevation_percentiles(
    elevation_grid: np.ndarray, width: int, height: int
) -> Dict[Point, float]:
    """
    Calculate elevation percentile for each tile.

    Args:
        elevation_grid: Grid of elevation values at subsquare resolution
        width: Number of tiles wide
        height: Number of tiles tall

    Returns dict mapping (x, y) -> percentile (0.0 = lowest, 1.0 = highest)
    """
    elevation_data = []
    for x in range(width):
        for y in range(height):
            # Get elevation from center subsquare of tile
            center_sx = x * 3 + 1
            center_sy = y * 3 + 1
            elev = elevation_grid[center_sx, center_sy]
            elevation_data.append((elev, (x, y)))
    elevation_data.sort(key=lambda e: e[0])

    percentiles = {}
    total = len(elevation_data)
    for i, (elev, pos) in enumerate(elevation_data):
        percentiles[pos] = i / max(1, total - 1)
    return percentiles


def invalidate_all_appearances(tiles: List[List[Tile]], width: int, height: int) -> None:
    """Invalidate cached appearance for all sub-squares.

    Called at day end to refresh visuals based on accumulated changes.
    """
    for x in range(width):
        for y in range(height):
            for row in tiles[x][y].subgrid:
                for subsquare in row:
                    subsquare.invalidate_appearance()


def recalculate_biomes(
    state: "GameState", moisture_grid: np.ndarray
) -> List[str]:
    """
    Recalculate biomes for all tiles based on current conditions.

    Called daily to allow landscape evolution based on moisture, etc.

    Args:
        state: GameState with terrain grids and kind_grid
        moisture_grid: (width, height) array of average moisture values

    Returns:
        List of messages to display to player
    """
    messages: List[str] = []
    percentiles = calculate_elevation_percentiles(state.elevation_grid, state.width, state.height)
    changes = 0

    for x in range(state.width):
        for y in range(state.height):
            # Don't change biome of tiles with depot structures
            # (Depot tile biome can now change naturally like any other tile)

            neighbor_positions = get_neighbors(x, y, state.width, state.height)
            elev_pct = percentiles.get((x, y), 0.5)
            avg_moisture = moisture_grid[x, y]
            new_biome = calculate_biome(state, x, y, neighbor_positions, elev_pct, avg_moisture)

            # Get current biome from kind_grid (center subsquare)
            center_sx = x * 3 + 1
            center_sy = y * 3 + 1
            old_biome = state.kind_grid[center_sx, center_sy]

            if new_biome != old_biome:
                # Update all 9 subsquares in this tile
                for local_x in range(3):
                    for local_y in range(3):
                        sx = x * 3 + local_x
                        sy = y * 3 + local_y
                        state.kind_grid[sx, sy] = new_biome
                changes += 1

    if changes > 0:
        messages.append(f"Landscape shifted: {changes} tiles changed biome.")

    return messages


# =============================================================================
# Map Generation
# =============================================================================

def _generate_wellsprings(tiles: List[List[Tile]], width: int, height: int, water_grid: np.ndarray) -> None:
    """
    Place wellsprings on the map, preferring lowland areas.

    Creates one primary wellspring in the lowest quarter of the map,
    plus 1-2 secondary smaller wellsprings.
    """
    # Sort tiles by elevation to find lowlands
    all_tiles = [(x, y, tiles[x][y].elevation) for x in range(width) for y in range(height)]
    all_tiles.sort(key=lambda t: t[2])

    # Primary wellspring in lowest quarter
    lowland_count = max(1, len(all_tiles) // 4)
    lowland_candidates = all_tiles[:lowland_count]
    px, py, _ = random.choice(lowland_candidates)
    tiles[px][py].kind = "wadi"
    # Primary wellspring: strong output to create visible water pooling
    tiles[px][py].wellspring_output = random.randint(40, 60)
    # Note: Initial subsurface water now set via subsurface_water_grid, not tile.water
    # Distribute initial surface water to sub-squares
    distribute_water_to_tile(tiles[px][py], 200, water_grid, px, py)

    # Secondary wellsprings
    secondary_count = random.randint(1, 2)
    attempts, placed = 0, 0
    while placed < secondary_count and attempts < 20:
        sx, sy = random.randrange(width), random.randrange(height)
        attempts += 1
        # Don't place on existing wellspring or map center (depot location)
        if tiles[sx][sy].wellspring_output > 0 or (sx, sy) == (width // 2, height // 2):
            continue
        # Secondary wellsprings: moderate output
        tiles[sx][sy].wellspring_output = random.randint(15, 30)
        # Note: Initial subsurface water now set via subsurface_water_grid, not tile.water
        # Distribute initial surface water to sub-squares
        distribute_water_to_tile(tiles[sx][sy], 80, water_grid, sx, sy)
        placed += 1




# =============================================================================
# Grid-Based Map Generation (Direct Array Generation)
# =============================================================================

def generate_grids_direct(grid_width: int, grid_height: int) -> Dict:
    """
    Generate map data directly as NumPy arrays (array-first approach).

    Creates a varied desert landscape at grid resolution without intermediate
    Tile objects. Uses WFC-style biome generation for natural clustering.

    Args:
        grid_width: Grid width (e.g., 180 for 60 tiles × 3)
        grid_height: Grid height (e.g., 135 for 45 tiles × 3)

    Returns:
        Dictionary with all grid arrays:
            - terrain_layers: (6, grid_w, grid_h) depth of each soil layer
            - terrain_materials: (6, grid_w, grid_h) material names
            - subsurface_water_grid: (6, grid_w, grid_h) water in each layer
            - bedrock_base: (grid_w, grid_h) bedrock elevation baseline
            - wellspring_grid: (grid_w, grid_h) wellspring output per cell
            - water_grid: (grid_w, grid_h) surface water
            - kind_grid: (grid_w, grid_h) biome type (temporary, for tile compatibility)
    """
    from ground import MATERIAL_LIBRARY

    # Initialize arrays
    terrain_layers = np.zeros((len(SoilLayer), grid_width, grid_height), dtype=np.int32)
    terrain_materials = np.zeros((len(SoilLayer), grid_width, grid_height), dtype='U20')
    subsurface_water_grid = np.zeros((len(SoilLayer), grid_width, grid_height), dtype=np.int32)
    bedrock_base = np.zeros((grid_width, grid_height), dtype=np.int32)
    wellspring_grid = np.zeros((grid_width, grid_height), dtype=np.int32)
    water_grid = np.zeros((grid_width, grid_height), dtype=np.int32)
    kind_grid = np.full((grid_width, grid_height), "flat", dtype='U20')

    # =============================================================================
    # TUNABLE BIOME GENERATION PARAMETERS
    # =============================================================================

    # Base biome weights for WFC (higher = more common)
    # TODO: Consider elevation in biome selection (wadis in lowlands, dunes in highlands)
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}

    # Adjacency preferences (biome -> neighbor biome -> bonus weight)
    # Controls how biomes cluster together
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    # Depth variations by biome (in meters)
    # TODO: Adjust depth ranges to ensure more terrain above sea level
    depth_map = {
        "dune": (1.5, 2.5),
        "flat": (1.0, 2.0),
        "wadi": (0.5, 1.2),
        "rock": (0.2, 0.6),
        "salt": (0.8, 1.5),
    }

    # WFC generation parameters
    WFC_SEED_PERCENTAGE = 0.05  # Percentage of cells to seed initially (0.05 = 5%)
    WFC_INFLUENCE_NOISE = 0.5   # Random noise added to influence scores (lower = more clustered)

    # Random bedrock baseline
    bedrock_base_elev = elevation_to_units(random.uniform(-2.5, -2.0))
    bedrock_base[:] = bedrock_base_elev

    # Generate biomes using WFC with convolution-based neighbor influence
    # Multi-pass approach: iteratively assign biomes using vectorized influence calculation

    # 4-connected neighbor kernel (cross pattern)
    kernel = np.array([[0, 1, 0],
                       [1, 0, 1],
                       [0, 1, 0]], dtype=np.float32)

    # Track which cells have been assigned
    assigned = np.zeros((grid_width, grid_height), dtype=bool)

    # Seed initial cells randomly for diversity
    biome_types = list(base_weights.keys())
    num_cells = grid_width * grid_height
    seed_count = max(100, int(num_cells * WFC_SEED_PERCENTAGE))

    seed_positions = [(np.random.randint(0, grid_width), np.random.randint(0, grid_height))
                      for _ in range(seed_count * 2)]  # Generate extra to account for collisions

    seeds_placed = 0
    for gx, gy in seed_positions:
        if seeds_placed >= seed_count:
            break
        if not assigned[gx, gy]:
            # Weight by base weights for initial seeds
            biome = random.choices(biome_types, weights=[base_weights[b] for b in biome_types])[0]
            kind_grid[gx, gy] = biome
            assigned[gx, gy] = True
            seeds_placed += 1

    # Process in waves until all cells assigned
    while np.sum(assigned) < num_cells:
        # For each biome type, create a binary mask of currently assigned cells
        biome_masks = {}
        for biome in biome_types:
            biome_masks[biome] = (kind_grid == biome).astype(np.float32)

        # Calculate influence scores for each target biome using convolution
        influence_grids = {}
        for target_biome in biome_types:
            # Start with base weight
            influence = np.full((grid_width, grid_height), base_weights[target_biome], dtype=np.float32)

            # Add adjacency bonuses from neighboring biomes
            adjacency_prefs = adjacency.get(target_biome, {})
            for source_biome, bonus in adjacency_prefs.items():
                if source_biome in biome_masks:
                    # Convolve to count neighbors of this type, multiply by bonus
                    neighbor_count = ndimage.convolve(biome_masks[source_biome], kernel, mode='constant', cval=0)
                    influence += neighbor_count * bonus

            influence_grids[target_biome] = influence

        # Stack influence grids for vectorized argmax
        influence_stack = np.stack([influence_grids[b] for b in biome_types], axis=0)

        # Select biomes for unassigned cells (with some randomness)
        # Add small random noise to break ties and create variation
        noise = np.random.uniform(0, WFC_INFLUENCE_NOISE, influence_stack.shape)
        influence_with_noise = influence_stack + noise

        # Find best biome for each cell
        best_biome_idx = np.argmax(influence_with_noise, axis=0)

        # Assign biomes to a random subset of unassigned cells (for wave effect)
        unassigned_coords = np.argwhere(~assigned)
        if len(unassigned_coords) > 0:
            # Assign 20-40% of remaining cells per wave for organic growth
            batch_size = max(1, int(len(unassigned_coords) * np.random.uniform(0.2, 0.4)))
            batch_indices = np.random.choice(len(unassigned_coords), size=batch_size, replace=False)

            for idx in batch_indices:
                gx, gy = unassigned_coords[idx]
                biome_idx = best_biome_idx[gx, gy]
                kind_grid[gx, gy] = biome_types[biome_idx]
                assigned[gx, gy] = True

    # Phase 2: Vectorized terrain property assignment based on biome grid
    # Generate random variations for each cell
    from config import DEPTH_UNIT_MM
    bedrock_variation = np.random.uniform(-0.3, 0.3, (grid_width, grid_height))
    bedrock_base[:] = bedrock_base_elev + (bedrock_variation * 1000 / DEPTH_UNIT_MM).astype(np.int32)

    # Depth variation per biome
    depth_grids = {}
    for biome, (min_depth, max_depth) in depth_map.items():
        mask = (kind_grid == biome)
        depth_random = np.random.uniform(min_depth, max_depth, (grid_width, grid_height))
        depth_grids[biome] = np.where(mask,
            (depth_random * 1000 / DEPTH_UNIT_MM).astype(np.int32),
            0
        )

    # Combine depth grids
    total_soil_depth = sum(depth_grids.values())

    # Distribute soil depth across layers (vectorized)
    terrain_layers[SoilLayer.REGOLITH] = (total_soil_depth * 0.30).astype(np.int32)
    terrain_layers[SoilLayer.SUBSOIL] = (total_soil_depth * 0.30).astype(np.int32)
    terrain_layers[SoilLayer.ELUVIATION] = (total_soil_depth * 0.15).astype(np.int32)
    terrain_layers[SoilLayer.TOPSOIL] = (total_soil_depth * 0.20).astype(np.int32)
    terrain_layers[SoilLayer.ORGANICS] = (total_soil_depth * 0.05).astype(np.int32)

    # Assign materials based on biome (vectorized with masks)
    # Dune biome
    dune_mask = (kind_grid == "dune")
    terrain_materials[SoilLayer.TOPSOIL][dune_mask] = "sand"
    terrain_materials[SoilLayer.ELUVIATION][dune_mask] = "silt"
    terrain_materials[SoilLayer.SUBSOIL][dune_mask] = "sand"
    terrain_materials[SoilLayer.REGOLITH][dune_mask] = "gravel"

    # Rock biome
    rock_mask = (kind_grid == "rock")
    terrain_materials[SoilLayer.TOPSOIL][rock_mask] = "rock"
    terrain_materials[SoilLayer.ELUVIATION][rock_mask] = "rock"
    terrain_materials[SoilLayer.SUBSOIL][rock_mask] = "rock"
    terrain_materials[SoilLayer.REGOLITH][rock_mask] = "rock"

    # Wadi biome
    wadi_mask = (kind_grid == "wadi")
    terrain_materials[SoilLayer.TOPSOIL][wadi_mask] = "silt"
    terrain_materials[SoilLayer.ELUVIATION][wadi_mask] = "silt"
    terrain_materials[SoilLayer.SUBSOIL][wadi_mask] = "clay"
    terrain_materials[SoilLayer.REGOLITH][wadi_mask] = "gravel"

    # Salt biome
    salt_mask = (kind_grid == "salt")
    terrain_materials[SoilLayer.TOPSOIL][salt_mask] = "sand"
    terrain_materials[SoilLayer.ELUVIATION][salt_mask] = "silt"
    terrain_materials[SoilLayer.SUBSOIL][salt_mask] = "silt"
    terrain_materials[SoilLayer.REGOLITH][salt_mask] = "gravel"

    # Flat biome (default)
    flat_mask = (kind_grid == "flat")
    terrain_materials[SoilLayer.TOPSOIL][flat_mask] = "dirt"
    terrain_materials[SoilLayer.ELUVIATION][flat_mask] = "silt"
    terrain_materials[SoilLayer.SUBSOIL][flat_mask] = "clay"
    terrain_materials[SoilLayer.REGOLITH][flat_mask] = "gravel"

    # Universal materials
    terrain_materials[SoilLayer.ORGANICS, :, :] = "humus"
    terrain_materials[SoilLayer.BEDROCK, :, :] = "bedrock"

    # Vectorized water table saturation
    # For each cell, saturate regolith based on material porosity
    regolith_depths = terrain_layers[SoilLayer.REGOLITH]
    # Build porosity grid from material names
    porosity_values = np.zeros_like(regolith_depths, dtype=np.float32)
    for mat_name, props in MATERIAL_LIBRARY.items():
        mat_mask = (terrain_materials[SoilLayer.REGOLITH] == mat_name)
        porosity_values[mat_mask] = props.porosity

    max_water = ((regolith_depths * porosity_values) // 100).astype(np.int32)
    subsurface_water_grid[SoilLayer.REGOLITH] = max_water

    # Generate wellsprings at tile centers (prefer lowland areas)
    # Calculate elevations for all tile center cells
    tile_width = grid_width // 3
    tile_height = grid_height // 3
    elev_list = []
    for tx in range(tile_width):
        for ty in range(tile_height):
            # Get center cell of this tile's 3x3 region
            center_gx = tx * 3 + 1
            center_gy = ty * 3 + 1
            if center_gx < grid_width and center_gy < grid_height:
                elev = bedrock_base[center_gx, center_gy] + np.sum(terrain_layers[:, center_gx, center_gy])
                elev_list.append((elev, center_gx, center_gy, tx, ty))
    elev_list.sort(key=lambda e: e[0])

    # Primary wellspring in lowest quarter
    lowland_count = max(1, len(elev_list) // 4)
    lowland_candidates = elev_list[:lowland_count]
    _, px, py, tile_x, tile_y = random.choice(lowland_candidates)
    # Mark entire tile region as wadi
    for dx in range(3):
        for dy in range(3):
            gx = tile_x * 3 + dx
            gy = tile_y * 3 + dy
            if gx < grid_width and gy < grid_height:
                kind_grid[gx, gy] = "wadi"
    wellspring_grid[px, py] = random.randint(40, 60)  # Strong output
    subsurface_water_grid[SoilLayer.REGOLITH, px, py] += 100
    water_grid[px, py] += 20

    # Secondary wellsprings (1-2)
    secondary_count = random.randint(1, 2)
    attempts, placed = 0, 0
    center_tile_x, center_tile_y = tile_width // 2, tile_height // 2
    while placed < secondary_count and attempts < 20:
        rand_tile_x = random.randrange(tile_width)
        rand_tile_y = random.randrange(tile_height)
        sx = rand_tile_x * 3 + 1
        sy = rand_tile_y * 3 + 1
        attempts += 1
        # Don't place on existing wellspring or near center (depot location)
        if wellspring_grid[sx, sy] > 0 or (abs(rand_tile_x - center_tile_x) < 2 and abs(rand_tile_y - center_tile_y) < 2):
            continue
        wellspring_grid[sx, sy] = random.randint(15, 30)  # Moderate output
        subsurface_water_grid[SoilLayer.REGOLITH, sx, sy] += 50
        water_grid[sx, sy] += 10
        placed += 1

    # Don't add surface water to wadi cells - let wellsprings fill them naturally

    return {
        "terrain_layers": terrain_layers,
        "terrain_materials": terrain_materials,
        "subsurface_water_grid": subsurface_water_grid,
        "bedrock_base": bedrock_base,
        "wellspring_grid": wellspring_grid,
        "water_grid": water_grid,
        "kind_grid": kind_grid,
    }
