# utils.py
"""
utils.py - Common utility functions for Kemet

Provides shared, stateless helper functions used across different modules.
"""
from __future__ import annotations

from typing import List, Tuple

Point = Tuple[int, int]


def get_neighbors(x: int, y: int, width: int, height: int) -> List[Point]:
    """Return list of valid orthogonal neighbors for a given position."""
    options = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            options.append((nx, ny))
    return options


def clamp(val: float, low: float, high: float) -> float:
    """Clamp a value between low and high bounds."""
    return max(low, min(high, val))


# =============================================================================
# Distance and Range Utilities (moved from subgrid.py)
# =============================================================================

def chebyshev_distance(p1: Point, p2: Point) -> int:
    """Chebyshev (chessboard) distance between two points.

    This is the number of king moves on a chessboard.
    Max of horizontal and vertical distance.

    Example: (0,0) to (3,2) -> 3
    """
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))


def manhattan_distance(p1: Point, p2: Point) -> int:
    """Manhattan (taxicab) distance between two points.

    Sum of horizontal and vertical distance.

    Example: (0,0) to (3,2) -> 5
    """
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


def is_in_range(player_pos: Point, target_pos: Point,
                interaction_range: int) -> bool:
    """Check if target is within interaction range of player.

    Uses Chebyshev distance for square-shaped range.
    """
    return chebyshev_distance(player_pos, target_pos) <= interaction_range


def get_subsquares_in_range(center: Point, interaction_range: int,
                            width: int, height: int) -> List[Point]:
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


def clamp_to_range(player_pos: Point, target_pos: Point,
                   interaction_range: int) -> Point:
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


def clamp_to_bounds(pos: Point, width: int, height: int) -> Point:
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
# 8-Neighbor Utilities (moved from subgrid.py)
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
                        direction: Point) -> Point:
    """Get neighboring grid cell coords in given direction.

    Args:
        sub_x, sub_y: Current grid cell world coords
        direction: (dx, dy) offset

    Returns:
        Neighboring grid cell world coords
    """
    return sub_x + direction[0], sub_y + direction[1]


def is_on_range_edge(pos: Point, center: Point,
                     interaction_range: int) -> bool:
    """Check if position is on the edge of the interaction range.

    Used for rendering range boundary indicators.
    """
    dist = chebyshev_distance(pos, center)
    return dist == interaction_range
