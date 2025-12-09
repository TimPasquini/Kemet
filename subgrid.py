"""Sub-grid system for fine-grained surface interactions.

Each simulation tile is divided into a 3x3 grid of sub-squares.
Sub-squares are independent units - water flows freely across tile boundaries.
The 3x3 grouping is purely organizational (storage + relation to subsurface simulation).
"""

from dataclasses import dataclass
from typing import Tuple, Optional, List

SUBGRID_SIZE = 3  # 3x3 sub-squares per tile


@dataclass
class SubSquare:
    """A single sub-square within a tile.

    Attributes:
        elevation_offset: Height relative to tile base elevation (enables slopes within tile)
        surface_water: Water pooled on this sub-square (in same units as tile water)
        structure_id: Reference to structure occupying this sub-square, if any
    """
    elevation_offset: float = 0.0
    surface_water: int = 0
    structure_id: Optional[int] = None


# =============================================================================
# Coordinate Conversion Utilities
# =============================================================================

def tile_to_subgrid(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Convert tile coords to top-left sub-square coords.

    Example: tile (2, 3) -> sub-square (6, 9)
    """
    return (tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE)


def subgrid_to_tile(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Convert sub-square coords to containing tile coords.

    Example: sub-square (7, 10) -> tile (2, 3)
    """
    return (sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE)


def get_subsquare_index(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Get index within tile (0-2, 0-2) from world sub-coords.

    Example: sub-square (7, 10) -> index (1, 1) within its tile
    """
    return (sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE)


def tile_center_subsquare(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Get the center sub-square coords for a tile.

    Example: tile (2, 3) -> sub-square (7, 10) (center of 3x3)
    """
    return (tile_x * SUBGRID_SIZE + 1, tile_y * SUBGRID_SIZE + 1)


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
    """Get all sub-square coords within Chebyshev distance of center.

    Args:
        center: Center point (sub-square coords)
        interaction_range: Maximum Chebyshev distance
        width: Map width in sub-squares
        height: Map height in sub-squares

    Returns:
        List of (sub_x, sub_y) coords within range and map bounds
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
        player_pos: Player's sub-square position
        target_pos: Desired target position
        interaction_range: Maximum allowed distance

    Returns:
        Target position clamped to within range
    """
    dx = target_pos[0] - player_pos[0]
    dy = target_pos[1] - player_pos[1]
    dx = max(-interaction_range, min(interaction_range, dx))
    dy = max(-interaction_range, min(interaction_range, dy))
    return (player_pos[0] + dx, player_pos[1] + dy)


def clamp_to_bounds(pos: Tuple[int, int], width: int, height: int) -> Tuple[int, int]:
    """Clamp position to within map bounds.

    Args:
        pos: Position to clamp
        width: Map width in sub-squares
        height: Map height in sub-squares

    Returns:
        Position clamped to valid range
    """
    return (
        max(0, min(width - 1, pos[0])),
        max(0, min(height - 1, pos[1]))
    )


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
    """Get neighboring sub-square coords in given direction.

    Args:
        sub_x, sub_y: Current sub-square world coords
        direction: (dx, dy) offset

    Returns:
        Neighboring sub-square world coords
    """
    return (sub_x + direction[0], sub_y + direction[1])


def is_on_range_edge(pos: Tuple[int, int], center: Tuple[int, int],
                     interaction_range: int) -> bool:
    """Check if position is on the edge of the interaction range.

    Used for rendering range boundary indicators.
    """
    dist = chebyshev_distance(pos, center)
    return dist == interaction_range
