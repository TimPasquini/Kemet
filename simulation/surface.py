# simulation/surface.py
"""Sub-grid surface water flow simulation.

Water flows between sub-squares based on elevation differences.
Flow crosses tile boundaries seamlessly - sub-squares are independent units.

Key concepts:
- Each sub-square has its own surface_water amount
- Flow is 8-directional (cardinal + diagonal)
- Elevation = tile base elevation + sub-square elevation_offset
- Water flows from high to low, distributed proportionally
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Tuple

from config import SUBGRID_SIZE, SURFACE_FLOW_RATE, SURFACE_FLOW_THRESHOLD, SURFACE_SEEPAGE_RATE
from subgrid import NEIGHBORS_8, get_subsquare_index, get_subsquare_terrain

if TYPE_CHECKING:
    from mapgen import Tile

Point = Tuple[int, int]


def get_subsquare_elevation(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get absolute elevation of a sub-square in depth units."""
    # Tile's terrain surface elevation (in depth units) + sub-square offset
    base_elev = tile.terrain.get_surface_elevation()
    # Convert offset from meters to depth units (1 unit = 0.1m = 100mm)
    offset_units = int(tile.subgrid[local_x][local_y].elevation_offset * 10)
    return base_elev + offset_units


def get_subsquare_water_height(tile: "Tile", local_x: int, local_y: int) -> float:
    """Get water surface height (elevation + water depth) for a sub-square."""
    elev = get_subsquare_elevation(tile, local_x, local_y)
    water = tile.subgrid[local_x][local_y].surface_water
    return elev + water


def simulate_surface_flow(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
) -> None:
    """Simulate one tick of surface water flow at sub-grid resolution.

    Water flows from each sub-square to lower neighbors based on the
    difference in water surface height (elevation + water depth).

    Args:
        tiles: 2D list of tiles [x][y]
        width: Map width in tiles
        height: Map height in tiles
    """
    # World dimensions in sub-squares
    sub_width = width * SUBGRID_SIZE
    sub_height = height * SUBGRID_SIZE

    # Calculate all flow deltas first (don't modify during calculation)
    deltas: Dict[Point, int] = defaultdict(int)

    for sub_x in range(sub_width):
        for sub_y in range(sub_height):
            # Get tile and local coords for this sub-square
            tile_x = sub_x // SUBGRID_SIZE
            tile_y = sub_y // SUBGRID_SIZE
            local_x = sub_x % SUBGRID_SIZE
            local_y = sub_y % SUBGRID_SIZE

            tile = tiles[tile_x][tile_y]
            subsquare = tile.subgrid[local_x][local_y]

            # Skip if no water to flow
            if subsquare.surface_water <= 0:
                continue

            # Calculate water surface height at this sub-square
            my_height = get_subsquare_water_height(tile, local_x, local_y)

            # Find all lower neighbors
            flow_targets: List[Tuple[Point, float]] = []
            total_diff = 0.0

            for dx, dy in NEIGHBORS_8:
                n_sub_x = sub_x + dx
                n_sub_y = sub_y + dy

                # Bounds check
                if not (0 <= n_sub_x < sub_width and 0 <= n_sub_y < sub_height):
                    continue

                # Get neighbor's tile and local coords
                n_tile_x = n_sub_x // SUBGRID_SIZE
                n_tile_y = n_sub_y // SUBGRID_SIZE
                n_local_x = n_sub_x % SUBGRID_SIZE
                n_local_y = n_sub_y % SUBGRID_SIZE

                n_tile = tiles[n_tile_x][n_tile_y]
                n_height = get_subsquare_water_height(n_tile, n_local_x, n_local_y)

                # Check elevation difference
                diff = my_height - n_height
                if diff > SURFACE_FLOW_THRESHOLD:
                    flow_targets.append(((n_sub_x, n_sub_y), diff))
                    total_diff += diff

            if not flow_targets:
                continue

            # Calculate how much water can flow this tick
            transferable = (subsquare.surface_water * SURFACE_FLOW_RATE) // 100

            if transferable <= 0:
                continue

            # Distribute water proportionally to elevation differences
            total_transferred = 0
            for (n_sub_x, n_sub_y), diff in flow_targets:
                portion = int((transferable * diff) / total_diff) if total_diff > 0 else 0
                if portion > 0:
                    deltas[(n_sub_x, n_sub_y)] += portion
                    total_transferred += portion

            # Record loss from source
            if total_transferred > 0:
                deltas[(sub_x, sub_y)] -= total_transferred

    # Apply all deltas and check for visual threshold changes
    for (sub_x, sub_y), delta in deltas.items():
        tile_x = sub_x // SUBGRID_SIZE
        tile_y = sub_y // SUBGRID_SIZE
        local_x = sub_x % SUBGRID_SIZE
        local_y = sub_y % SUBGRID_SIZE

        tile = tiles[tile_x][tile_y]
        subsquare = tile.subgrid[local_x][local_y]
        subsquare.surface_water = max(0, subsquare.surface_water + delta)
        # Check if water crossed a visual threshold (dry/wet/flooded)
        subsquare.check_water_threshold()


def simulate_surface_seepage(
    tiles: List[List["Tile"]],
    width: int,
    height: int,
) -> None:
    """Simulate surface water seeping into the topmost soil layer.

    Water on each sub-square seeps down into the tile's soil based on
    the permeability of the exposed material.

    Args:
        tiles: 2D list of tiles [x][y]
        width: Map width in tiles
        height: Map height in tiles
    """
    from ground import MATERIAL_LIBRARY, SoilLayer

    for tile_x in range(width):
        for tile_y in range(height):
            tile = tiles[tile_x][tile_y]

            # Get the topmost soil layer for this tile
            exposed_layer = tile.terrain.get_exposed_layer()
            if exposed_layer == SoilLayer.BEDROCK:
                continue  # Can't seep into bedrock

            material = tile.terrain.get_layer_material(exposed_layer)
            props = MATERIAL_LIBRARY.get(material)
            if not props or props.permeability_vertical <= 0:
                continue

            # Calculate capacity remaining in the topmost layer
            max_storage = tile.terrain.get_max_water_storage(exposed_layer)
            current_water = tile.water.get_layer_water(exposed_layer)
            available_capacity = max_storage - current_water

            if available_capacity <= 0:
                continue  # Layer is saturated

            # Process each sub-square
            for row in tile.subgrid:
                for subsquare in row:
                    if subsquare.surface_water <= 0:
                        continue

                    # Calculate seepage amount based on permeability
                    seep_rate = (SURFACE_SEEPAGE_RATE * props.permeability_vertical) // 100
                    seep_amount = (subsquare.surface_water * seep_rate) // 100

                    # Cap at available capacity (shared across all sub-squares)
                    seep_amount = min(seep_amount, available_capacity)

                    if seep_amount > 0:
                        subsquare.surface_water -= seep_amount
                        tile.water.add_layer_water(exposed_layer, seep_amount)
                        available_capacity -= seep_amount

                    if available_capacity <= 0:
                        break
                if available_capacity <= 0:
                    break


def get_tile_surface_water(tile: "Tile") -> int:
    """Get total surface water across all sub-squares in a tile.

    Useful for compatibility with tile-level systems (evaporation, etc.).
    """
    total = 0
    for row in tile.subgrid:
        for subsquare in row:
            total += subsquare.surface_water
    return total


def set_tile_surface_water(tile: "Tile", amount: int) -> None:
    """Distribute water amount across tile's sub-squares by elevation.

    Lower sub-squares receive more water (natural pooling behavior).

    Args:
        tile: Tile to distribute water to
        amount: Total water amount to distribute
    """
    if amount <= 0:
        # Clear all water
        for row in tile.subgrid:
            for subsquare in row:
                subsquare.surface_water = 0
        return

    # Calculate inverse elevation weights (lower = higher weight)
    weights: List[Tuple[int, int, float]] = []
    total_weight = 0.0

    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            elev = get_subsquare_elevation(tile, lx, ly)
            # Inverse weight - add small offset to avoid division by zero
            weight = 1.0 / (elev + 100.0)
            weights.append((lx, ly, weight))
            total_weight += weight

    # Distribute proportionally
    distributed = 0
    for i, (lx, ly, weight) in enumerate(weights):
        if i == len(weights) - 1:
            # Last one gets remainder to avoid rounding errors
            portion = amount - distributed
        else:
            portion = int((amount * weight) / total_weight)

        tile.subgrid[lx][ly].surface_water = max(0, portion)
        distributed += portion


def distribute_upward_seepage(tile: "Tile", water_amount: int) -> None:
    """Distribute water seeping up from subsurface to sub-squares.

    Water emerges weighted by inverse elevation - lowest sub-squares
    receive the most water (natural spring behavior).

    Args:
        tile: Tile receiving upward seepage
        water_amount: Amount of water emerging from below
    """
    if water_amount <= 0:
        return

    # Calculate weights based on inverse elevation
    weights: List[Tuple[int, int, float]] = []
    total_weight = 0.0

    for lx in range(SUBGRID_SIZE):
        for ly in range(SUBGRID_SIZE):
            offset = tile.subgrid[lx][ly].elevation_offset
            # Lower elevation = higher weight
            # Use 1.0 / (offset + 0.1) to give lowest spots most water
            # but still give some to higher spots
            weight = 1.0 / (offset + 0.15)
            weights.append((lx, ly, weight))
            total_weight += weight

    # Distribute water and check thresholds
    distributed = 0
    for i, (lx, ly, weight) in enumerate(weights):
        if i == len(weights) - 1:
            portion = water_amount - distributed
        else:
            portion = int((water_amount * weight) / total_weight)

        subsquare = tile.subgrid[lx][ly]
        subsquare.surface_water += max(0, portion)
        subsquare.check_water_threshold()
        distributed += portion
