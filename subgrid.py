"""Grid coordinate conversion utilities for tile-based systems.

DEPRECATED - TO BE REMOVED IN PHASE 3 (Atmosphere Migration):
This module provides coordinate conversion between "tiles" (3×3 grid cell regions)
and individual grid cells. These conversions exist solely for compatibility with
the legacy atmosphere system which operates on tile coordinates.

After Phase 3 atmosphere vectorization, all systems will use grid coordinates
directly (0-179, 0-134) and this module will be deleted.

Current usage:
- Tile grouping: Each "tile" is a 3×3 region of grid cells
- Grid cells are independent units - water flows freely across tile boundaries
- All game state is stored in NumPy grids at grid cell resolution (180×135)
"""
from __future__ import annotations

from typing import Tuple, List

# DEPRECATED - Import from config.py instead. Will be removed in Phase 3.
from config import SUBGRID_SIZE


# =============================================================================
# Coordinate Conversion Utilities
# =============================================================================

def tile_to_subgrid(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Convert tile coords to top-left grid cell coords.

    DEPRECATED - For use with legacy atmosphere system only.

    Example: tile (2, 3) -> grid cell (6, 9)
    """
    return tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE


def subgrid_to_tile(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Convert grid cell coords to containing tile coords.

    DEPRECATED - For use with legacy atmosphere system only.

    Example: grid cell (7, 10) -> tile (2, 3)
    """
    return sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE


def get_subsquare_index(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Get index within tile (0-2, 0-2) from world grid coords.

    DEPRECATED - For use with legacy atmosphere system only.

    Example: grid cell (7, 10) -> index (1, 1) within its tile
    """
    return sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE


def tile_center_subsquare(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Get the center grid cell coords for a tile.

    DEPRECATED - For use with legacy atmosphere system only.

    Example: tile (2, 3) -> grid cell (7, 10) (center of 3x3)
    """
    return tile_x * SUBGRID_SIZE + 1, tile_y * SUBGRID_SIZE + 1


# =============================================================================
# Distance and Range Utilities
# =============================================================================

def chebyshev_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    """Chebyshev (chessboard) distance between two points.

    This is the number of king moves on a chessboard.
    Max of horizontal and vertical distance.

    Example: (0,0) to (3,2) -> 3
    """
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))


def manhattan_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    """Manhattan (taxicab) distance between two points.

    Sum of horizontal and vertical distance.

    Example: (0,0) to (3,2) -> 5
    """
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


def is_in_range(player_pos: Tuple[int, int], target_pos: Tuple[int, int],
                interaction_range: int) -> bool:
    """Check if target is within interaction range of player.

    Uses Chebyshev distance for square-shaped range.
    """
    return chebyshev_distance(player_pos, target_pos) <= interaction_range


def get_subsquares_in_range(center: Tuple[int, int], interaction_range: int,
                            width: int, height: int) -> List[Tuple[int, int]]:
    """Get all grid cell coords within Chebyshev distance of center.

    Args:
        center: Center point (grid cell coords)
        interaction_range: Maximum Chebyshev distance
        width: Map width in grid cells
        height: Map height in grid cells

    Returns:
        List of (sx, sy) coords within range and map bounds
    """
    result = []
    for dx in range(-interaction_range, interaction_range + 1):
        for dy in range(-interaction_range, interaction_range + 1):
            x, y = center[0] + dx, center[1] + dy
            if 0 <= x < width and 0 <= y < height:
                result.append((x, y))
    return result


def clamp_to_range(player_pos: Tuple[int, int], target_pos: Tuple[int, int],
                   interaction_range: int) -> Tuple[int, int]:
    """Clamp target to within range of player.

    If target is outside range, returns the closest point within range
    in the direction of target.

    Args:
        player_pos: Player's grid cell position
        target_pos: Desired target position
        interaction_range: Maximum allowed distance

    Returns:
        Target position clamped to within range
    """
    dx = target_pos[0] - player_pos[0]
    dy = target_pos[1] - player_pos[1]
    dx = max(-interaction_range, min(interaction_range, dx))
    dy = max(-interaction_range, min(interaction_range, dy))
    return player_pos[0] + dx, player_pos[1] + dy


def clamp_to_bounds(pos: Tuple[int, int], width: int, height: int) -> Tuple[int, int]:
    """Clamp position to within map bounds.

    Args:
        pos: Position to clamp
        width: Map width in grid cells
        height: Map height in grid cells

    Returns:
        Position clamped to valid range
    """
    return max(0, min(width - 1, pos[0])), max(0, min(height - 1, pos[1]))


# =============================================================================
# 8-Neighbor Utilities (for water flow)
# =============================================================================

# 8 neighboring directions (cardinal + diagonal)
NEIGHBORS_8 = [
    (-1, -1), (0, -1), (1, -1),
    (-1,  0),          (1,  0),
    (-1,  1), (0,  1), (1,  1),
]

# 4 cardinal directions only
NEIGHBORS_4 = [
    (0, -1),           # up
    (-1, 0), (1, 0),   # left, right
    (0,  1),           # down
]


def get_neighbor_coords(sub_x: int, sub_y: int,
                        direction: Tuple[int, int]) -> Tuple[int, int]:
    """Get neighboring grid cell coords in given direction.

    Args:
        sub_x, sub_y: Current grid cell world coords
        direction: (dx, dy) offset

    Returns:
        Neighboring grid cell world coords
    """
    return sub_x + direction[0], sub_y + direction[1]


def is_on_range_edge(pos: Tuple[int, int], center: Tuple[int, int],
                     interaction_range: int) -> bool:
    """Check if position is on the edge of the interaction range.

    Used for rendering range boundary indicators.
    """
    dist = chebyshev_distance(pos, center)
    return dist == interaction_range
