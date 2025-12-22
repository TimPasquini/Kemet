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
from typing import Deque, Dict, List, Tuple

import numpy as np
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
from water import WaterColumn
from utils import get_neighbors
from config import SUBGRID_SIZE
from subgrid import SubSquare
from simulation.surface import distribute_water_to_tile

Point = Tuple[int, int]


# =============================================================================
# Tile Class
# =============================================================================

def _create_default_subgrid() -> List[List[SubSquare]]:
    """Create a 3x3 subgrid with slight elevation variation."""
    subgrid = []
    for sx in range(SUBGRID_SIZE):
        row = []
        for sy in range(SUBGRID_SIZE):
            # Quantize to 0.1m steps so physics engine (1 unit = 0.1m) sees the variation
            offset = random.choice([-0.1, 0.0, 0.1])
            row.append(SubSquare(elevation_offset=offset))
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
    depot: bool = False                 # Is this the player's depot?
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

    def get_subsquare_elevation(self, local_x: int, local_y: int) -> float:
        """Get absolute elevation of a subsquare in meters."""
        return self.elevation + self.subgrid[local_x][local_y].elevation_offset


# =============================================================================
# Biome Calculation
# =============================================================================

def calculate_biome(tile: Tile, neighbor_tiles: List[Tile], elevation_percentile: float, avg_moisture: float) -> str:
    """
    Determine the biome type for a tile based on its properties.

    Args:
        tile: The tile to classify
        neighbor_tiles: Adjacent tiles for context
        elevation_percentile: 0.0-1.0 ranking of elevation (0=lowest, 1=highest)
        avg_moisture: Average moisture level for this tile

    Returns:
        Biome key string (e.g., "dune", "wadi", "rock")
    """
    soil_depth = tile.terrain.get_total_soil_depth()
    topsoil_material = tile.terrain.topsoil_material

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
    if elevation_percentile < 0.4 and avg_moisture < 15 and tile.terrain.organics_depth == 0:
        return "salt"

    # Follow neighbors if strong consensus
    if neighbor_tiles:
        neighbor_biomes = [n.kind for n in neighbor_tiles]
        biome_counts = Counter(neighbor_biomes)
        most_common_list = biome_counts.most_common(1)
        if most_common_list:
            most_common, count = most_common_list[0]
            if count >= 3 and most_common in ("dune", "flat", "wadi"):
                return most_common

    return "flat"


def calculate_elevation_percentiles(
    tiles: List[List[Tile]], width: int, height: int
) -> Dict[Point, float]:
    """
    Calculate elevation percentile for each tile.

    Returns dict mapping (x, y) -> percentile (0.0 = lowest, 1.0 = highest)
    """
    elevation_data = []
    for x in range(width):
        for y in range(height):
            elevation_data.append((tiles[x][y].elevation, (x, y)))
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
    tiles: List[List[Tile]], width: int, height: int, moisture_grid: np.ndarray
) -> List[str]:
    """
    Recalculate biomes for all tiles based on current conditions.

    Called daily to allow landscape evolution based on moisture, etc.
    Also invalidates all appearance caches to refresh visuals.

    moisture_grid: (width, height) array of average moisture values
    Returns:
        List of messages to display to player
    """
    messages: List[str] = []
    percentiles = calculate_elevation_percentiles(tiles, width, height)
    changes = 0

    for x in range(width):
        for y in range(height):
            tile = tiles[x][y]
            if tile.depot:
                continue  # Don't change depot tile

            neighbor_tiles = [
                tiles[nx][ny]
                for nx, ny in get_neighbors(x, y, width, height)
            ]
            elev_pct = percentiles.get((x, y), 0.5)
            avg_moisture = moisture_grid[x, y]
            new_biome = calculate_biome(tile, neighbor_tiles, elev_pct, avg_moisture)

            if new_biome != tile.kind:
                tile.kind = new_biome
                changes += 1

    # Refresh all appearance caches at day end
    invalidate_all_appearances(tiles, width, height)

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
    tiles[px][py].water.add_layer_water(SoilLayer.REGOLITH, 200)
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
        tiles[sx][sy].water.add_layer_water(SoilLayer.REGOLITH, 100)
        # Distribute initial surface water to sub-squares
        distribute_water_to_tile(tiles[sx][sy], 80, water_grid, sx, sy)
        placed += 1


def generate_map(width: int, height: int, water_grid: np.ndarray) -> List[List[Tile]]:
    """
    Generate a procedural map using WFC-style weighted selection.

    Creates a varied desert landscape with biomes that cluster naturally.

    Args:
        width: Map width in tiles
        height: Map height in tiles

    Returns:
        2D list of Tiles [x][y]
    """
    # Base weights for each biome
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}

    # Adjacency preferences (biome -> neighbor biome -> bonus weight)
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    # Random bedrock base elevation
    bedrock_base = elevation_to_units(random.uniform(-2.5, -2.0))

    # Initialize all tiles as flat
    tiles: List[List[Tile]] = [
        [
            Tile(
                "flat",
                create_default_terrain(bedrock_base, elevation_to_units(1.0)),
                WaterColumn(),
                SurfaceTraits()
            )
            for _ in range(height)
        ]
        for _ in range(width)
    ]

    # Process tiles in random order for more natural results
    positions = [(x, y) for x in range(width) for y in range(height)]
    random.shuffle(positions)

    # Depth variations by biome
    depth_map = {
        "dune": (1.5, 2.5),
        "flat": (1.0, 2.0),
        "wadi": (0.5, 1.2),
        "rock": (0.2, 0.6),
        "salt": (0.8, 1.5),
    }

    for x, y in positions:
        # Get neighbor biomes for context
        neighbor_types = [tiles[nx][ny].kind for nx, ny in get_neighbors(x, y, width, height)]

        # Calculate weighted probabilities
        weighted: Dict[str, int] = {}
        for kind, base_w in base_weights.items():
            weight = base_w
            for n in neighbor_types:
                weight += adjacency.get(n, {}).get(kind, 0)
            weighted[kind] = weight

        # Select biome
        choice = random.choices(
            list(weighted.keys()),
            weights=list(weighted.values()),
            k=1
        )[0]

        # Create terrain with appropriate depth
        depth_range = depth_map[choice]
        bedrock_elev = bedrock_base + elevation_to_units(random.uniform(-0.3, 0.3))
        total_soil = elevation_to_units(random.uniform(*depth_range))

        tiles[x][y] = Tile(
            choice,
            create_default_terrain(bedrock_elev, total_soil),
            WaterColumn(),
            SurfaceTraits()
        )

        # Saturate regolith to create base water table
        regolith_capacity = tiles[x][y].terrain.get_max_water_storage(SoilLayer.REGOLITH)
        tiles[x][y].water.set_layer_water(SoilLayer.REGOLITH, regolith_capacity)

    # Add wellsprings
    _generate_wellsprings(tiles, width, height, water_grid)

    # Add surface water to wadis (distributed directly to sub-squares)
    for x in range(width):
        for y in range(height):
            tile = tiles[x][y]
            if tile.kind == "wadi":
                distribute_water_to_tile(tile, random.randint(5, 30), water_grid, x, y)

    return tiles


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
            - elevation_offset_grid: (grid_w, grid_h) fine elevation adjustments
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
    elevation_offset_grid = np.zeros((grid_width, grid_height), dtype=np.int32)
    wellspring_grid = np.zeros((grid_width, grid_height), dtype=np.int32)
    water_grid = np.zeros((grid_width, grid_height), dtype=np.int32)
    kind_grid = np.full((grid_width, grid_height), "flat", dtype='U20')

    # Base biome weights for WFC
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}

    # Adjacency preferences (biome -> neighbor biome -> bonus weight)
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    # Depth variations by biome (in meters)
    depth_map = {
        "dune": (1.5, 2.5),
        "flat": (1.0, 2.0),
        "wadi": (0.5, 1.2),
        "rock": (0.2, 0.6),
        "salt": (0.8, 1.5),
    }

    # Random bedrock baseline
    bedrock_base_elev = elevation_to_units(random.uniform(-2.5, -2.0))
    bedrock_base[:] = bedrock_base_elev

    # Generate biomes using WFC (at grid resolution)
    # Process in random order for more natural results
    positions = [(gx, gy) for gx in range(grid_width) for gy in range(grid_height)]
    random.shuffle(positions)

    for gx, gy in positions:
        # Get neighbor biomes for context (4-connected)
        neighbor_types = []
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nx, ny = gx + dx, gy + dy
            if 0 <= nx < grid_width and 0 <= ny < grid_height:
                neighbor_types.append(kind_grid[nx, ny])

        # Calculate weighted probabilities
        weighted: Dict[str, int] = {}
        for kind, base_w in base_weights.items():
            weight = base_w
            for n in neighbor_types:
                weight += adjacency.get(n, {}).get(kind, 0)
            weighted[kind] = weight

        # Select biome
        choice = random.choices(
            list(weighted.keys()),
            weights=list(weighted.values()),
            k=1
        )[0]
        kind_grid[gx, gy] = choice

        # Create terrain layers for this cell
        depth_range = depth_map[choice]
        bedrock_var = elevation_to_units(random.uniform(-0.3, 0.3))
        bedrock_base[gx, gy] = bedrock_base_elev + bedrock_var

        total_soil_depth = elevation_to_units(random.uniform(*depth_range))

        # Distribute soil depth across layers (simplified distribution)
        # Regolith: 30%, Subsoil: 40%, Topsoil: 25%, Organics: 5%
        terrain_layers[SoilLayer.REGOLITH, gx, gy] = int(total_soil_depth * 0.30)
        terrain_layers[SoilLayer.SUBSOIL, gx, gy] = int(total_soil_depth * 0.40)
        terrain_layers[SoilLayer.TOPSOIL, gx, gy] = int(total_soil_depth * 0.25)
        terrain_layers[SoilLayer.ORGANICS, gx, gy] = int(total_soil_depth * 0.05)

        # Assign materials based on biome
        if choice == "dune":
            terrain_materials[SoilLayer.TOPSOIL, gx, gy] = "sand"
            terrain_materials[SoilLayer.SUBSOIL, gx, gy] = "sand"
            terrain_materials[SoilLayer.REGOLITH, gx, gy] = "gravel"
        elif choice == "rock":
            terrain_materials[SoilLayer.TOPSOIL, gx, gy] = "rock"
            terrain_materials[SoilLayer.SUBSOIL, gx, gy] = "rock"
            terrain_materials[SoilLayer.REGOLITH, gx, gy] = "rock"
        elif choice == "wadi":
            terrain_materials[SoilLayer.TOPSOIL, gx, gy] = "silt"
            terrain_materials[SoilLayer.SUBSOIL, gx, gy] = "clay"
            terrain_materials[SoilLayer.REGOLITH, gx, gy] = "gravel"
        elif choice == "salt":
            terrain_materials[SoilLayer.TOPSOIL, gx, gy] = "sand"
            terrain_materials[SoilLayer.SUBSOIL, gx, gy] = "silt"
            terrain_materials[SoilLayer.REGOLITH, gx, gy] = "gravel"
        else:  # flat
            terrain_materials[SoilLayer.TOPSOIL, gx, gy] = "dirt"
            terrain_materials[SoilLayer.SUBSOIL, gx, gy] = "clay"
            terrain_materials[SoilLayer.REGOLITH, gx, gy] = "gravel"

        terrain_materials[SoilLayer.ORGANICS, gx, gy] = "humus"
        terrain_materials[SoilLayer.BEDROCK, gx, gy] = "bedrock"

        # Add fine elevation variation (sub-tile resolution)
        offset = random.choice([-1, 0, 1])  # ±0.1m in units (1 unit = 0.1m)
        elevation_offset_grid[gx, gy] = offset

        # Saturate regolith layer to create water table
        regolith_depth = terrain_layers[SoilLayer.REGOLITH, gx, gy]
        material_name = terrain_materials[SoilLayer.REGOLITH, gx, gy]
        props = MATERIAL_LIBRARY.get(material_name)
        if props and regolith_depth > 0:
            porosity = props.porosity
            max_water = (regolith_depth * porosity) // 100
            subsurface_water_grid[SoilLayer.REGOLITH, gx, gy] = max_water

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
                elev = bedrock_base[center_gx, center_gy] + np.sum(terrain_layers[:, center_gx, center_gy]) + elevation_offset_grid[center_gx, center_gy]
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
        "elevation_offset_grid": elevation_offset_grid,
        "wellspring_grid": wellspring_grid,
        "water_grid": water_grid,
        "kind_grid": kind_grid,
    }
