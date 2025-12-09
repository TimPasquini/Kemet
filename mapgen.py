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
from config import MOISTURE_HISTORY_MAX, SUBGRID_SIZE
from subgrid import SubSquare

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

def _create_default_subgrid() -> List[List[SubSquare]]:
    """Create a 3x3 subgrid with slight elevation variation."""
    subgrid = []
    for sx in range(SUBGRID_SIZE):
        row = []
        for sy in range(SUBGRID_SIZE):
            # Small random elevation offset to create micro-terrain
            # Range: -0.05 to +0.05 meters
            offset = random.uniform(-0.05, 0.05)
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
    """
    kind: str                           # Biome type key into TILE_TYPES
    terrain: TerrainColumn              # Soil layers and elevation
    water: WaterColumn                  # Water storage
    surface: SurfaceTraits              # Surface features (trench, etc.)
    wellspring_output: int = 0          # Water output per tick (0 = not a wellspring)
    depot: bool = False                 # Is this the player's depot?
    moisture_history: List[int] = field(default_factory=list)
    subgrid: List[List[SubSquare]] = field(default_factory=_create_default_subgrid)

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

    def get_subsquare(self, local_x: int, local_y: int) -> SubSquare:
        """Get a subsquare by local index (0-2, 0-2)."""
        return self.subgrid[local_x][local_y]

    def get_subsquare_elevation(self, local_x: int, local_y: int) -> float:
        """Get absolute elevation of a subsquare in meters."""
        return self.elevation + self.subgrid[local_x][local_y].elevation_offset


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

    # Add surface water to wadis and distribute to sub-squares
    for x in range(width):
        for y in range(height):
            tile = tiles[x][y]
            if tile.kind == "wadi":
                tile.water.surface_water += random.randint(5, 30)

            # Distribute any tile surface water to sub-squares
            if tile.water.surface_water > 0:
                _distribute_surface_water_to_subgrid(tile)

    return tiles


def _distribute_surface_water_to_subgrid(tile: Tile) -> None:
    """Distribute tile's surface water to sub-squares by elevation.

    Lower sub-squares receive more water (natural pooling).
    Clears the tile's WaterColumn.surface_water after distribution.
    """
    amount = tile.water.surface_water
    if amount <= 0:
        return

    # Calculate inverse elevation weights
    weights = []
    total_weight = 0.0

    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            offset = tile.subgrid[lx][ly].elevation_offset
            # Lower elevation = higher weight
            weight = 1.0 / (offset + 0.15)
            weights.append((lx, ly, weight))
            total_weight += weight

    # Distribute proportionally
    distributed = 0
    for i, (lx, ly, weight) in enumerate(weights):
        if i == len(weights) - 1:
            portion = amount - distributed
        else:
            portion = int((amount * weight) / total_weight)

        tile.subgrid[lx][ly].surface_water += max(0, portion)
        distributed += portion

    # Clear tile-level surface water (now in sub-squares)
    tile.water.surface_water = 0
