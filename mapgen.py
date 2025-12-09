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
from typing import Dict, List, Tuple

from ground import (
    TerrainColumn,
    SurfaceTraits,
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from water import WaterColumn
from utils import get_neighbors
from config import MOISTURE_HISTORY_MAX

Point = Tuple[int, int]


# =============================================================================
# Tile Types (Biomes)
# =============================================================================

@dataclass
class TileType:
    """Definition of a biome/tile type with its properties."""
    name: str
    char: str       # ASCII character for text rendering
    evap: int       # Base evaporation rate
    capacity: int   # Water holding capacity
    retention: int  # Water retention percentage


TILE_TYPES: Dict[str, TileType] = {
    "dune": TileType("dune", ".", evap=12, capacity=60, retention=5),
    "flat": TileType("flat", ",", evap=9, capacity=90, retention=8),
    "wadi": TileType("wadi", "w", evap=5, capacity=140, retention=20),
    "rock": TileType("rock", "^", evap=6, capacity=50, retention=2),
    "salt": TileType("salt", "_", evap=14, capacity=70, retention=3),
}


# =============================================================================
# Tile Class
# =============================================================================

@dataclass
class Tile:
    """
    A single map tile containing terrain, water, and surface information.
    """
    kind: str                           # Biome type key into TILE_TYPES
    terrain: TerrainColumn              # Soil layers and elevation
    water: WaterColumn                  # Water storage
    surface: SurfaceTraits              # Surface features (trench, etc.)
    wellspring_output: int = 0          # Water output per tick (0 = not a wellspring)
    depot: bool = False                 # Is this the player's depot?
    moisture_history: List[int] = field(default_factory=list)

    @property
    def elevation(self) -> float:
        """Surface elevation in meters."""
        return units_to_meters(self.terrain.get_surface_elevation())

    @property
    def hydration(self) -> float:
        """Total water in liters."""
        return self.water.total_water() / 10.0

    @property
    def trench(self) -> bool:
        """Whether this tile has a trench."""
        return self.surface.has_trench

    @trench.setter
    def trench(self, value: bool) -> None:
        self.surface.has_trench = value


# =============================================================================
# Biome Calculation
# =============================================================================

def update_moisture_history(tile: Tile) -> None:
    """Track moisture over time for biome calculations."""
    tile.moisture_history.append(tile.water.total_water())
    if len(tile.moisture_history) > MOISTURE_HISTORY_MAX:
        tile.moisture_history.pop(0)


def get_average_moisture(tile: Tile) -> float:
    """Get average moisture over recent history."""
    if not tile.moisture_history:
        return float(tile.water.total_water())
    return sum(tile.moisture_history) / len(tile.moisture_history)


def calculate_biome(tile: Tile, neighbor_tiles: List[Tile], elevation_percentile: float) -> str:
    """
    Determine the biome type for a tile based on its properties.

    Args:
        tile: The tile to classify
        neighbor_tiles: Adjacent tiles for context
        elevation_percentile: 0.0-1.0 ranking of elevation (0=lowest, 1=highest)

    Returns:
        Biome key string (e.g., "dune", "wadi", "rock")
    """
    avg_moisture = get_average_moisture(tile)
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


def recalculate_biomes(
    tiles: List[List[Tile]], width: int, height: int
) -> List[str]:
    """
    Recalculate biomes for all tiles based on current conditions.

    Called daily to allow landscape evolution based on moisture, etc.

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
            new_biome = calculate_biome(tile, neighbor_tiles, elev_pct)

            if new_biome != tile.kind:
                tile.kind = new_biome
                changes += 1

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
    tiles[px][py].wellspring_output = random.randint(8, 12)
    tiles[px][py].water.add_layer_water(SoilLayer.REGOLITH, 100)
    tiles[px][py].water.surface_water = 80

    # Secondary wellsprings
    secondary_count = random.randint(1, 2)
    attempts, placed = 0, 0
    while placed < secondary_count and attempts < 20:
        sx, sy = random.randrange(width), random.randrange(height)
        attempts += 1
        # Don't place on existing wellspring or map center (depot location)
        if tiles[sx][sy].wellspring_output > 0 or (sx, sy) == (width // 2, height // 2):
            continue
        tiles[sx][sy].wellspring_output = random.randint(2, 6)
        tiles[sx][sy].water.add_layer_water(SoilLayer.REGOLITH, 30)
        tiles[sx][sy].water.surface_water = 20
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

    # Add surface water to wadis
    for x in range(width):
        for y in range(height):
            if tiles[x][y].kind == "wadi":
                tiles[x][y].water.surface_water += random.randint(5, 30)

    return tiles
