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
        surface = sum(ss.surface_water for row in self.subgrid for ss in row)
        return (surface + self.water.total_subsurface_water()) / 10.0

    @property
    def trench(self) -> bool:
        """Whether this tile has a trench."""
        return self.surface.has_trench

    @trench.setter
    def trench(self, value: bool) -> None:
        self.surface.has_trench = value

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

def _generate_wellsprings(tiles: List[List[Tile]], width: int, height: int) -> None:
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
    distribute_water_to_tile(tiles[px][py], 200)

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
        distribute_water_to_tile(tiles[sx][sy], 80)
        placed += 1


def generate_map(width: int, height: int) -> List[List[Tile]]:
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
    _generate_wellsprings(tiles, width, height)

    # Add surface water to wadis (distributed directly to sub-squares)
    for x in range(width):
        for y in range(height):
            tile = tiles[x][y]
            if tile.kind == "wadi":
                distribute_water_to_tile(tile, random.randint(5, 30))

    return tiles
