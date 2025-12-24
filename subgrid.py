"""Sub-grid system for fine-grained surface interactions.

Each simulation tile is divided into a 3x3 grid of sub-squares.
Sub-squares are independent units - water flows freely across tile boundaries.
The 3x3 grouping is purely organizational (storage + relation to subsurface simulation).
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Tuple, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ground import TerrainColumn
    from mapgen import Tile

SUBGRID_SIZE = 3  # 3x3 sub-squares per tile


@dataclass
class SubSquare:
    """A single sub-square within a tile.

    Attributes:
        structure_id: Reference to structure occupying this sub-square, if any
        terrain_override: Optional independent terrain column for this sub-square.
            When None, the sub-square inherits terrain from its parent tile.
            When set, this sub-square has been modified independently.

    Visual appearance is cached and computed from environmental factors
    (exposed material, water state, organics). Call invalidate_appearance()
    when these factors change, or it will be recalculated at day end.
    """
    structure_id: Optional[int] = None
    terrain_override: Optional["TerrainColumn"] = None
    # Erosion system fields (sediment for immediate feedback)
    sediment_load: int = 0                      # Carried sediment amount (depth units)
    sediment_material: Optional[str] = None     # Material type of sediment
    # Daily pressure accumulators (reset on overnight processing)
    water_passage: float = 0.0                  # Sum of water that flowed through today
    wind_exposure: float = 0.0                  # Sum of wind pressure experienced today
    # Cached appearance (computed lazily, invalidated on changes)
    _cached_appearance: Optional[object] = field(default=None, repr=False)
    # Track water level for threshold-based invalidation
    _last_water_state: int = field(default=0, repr=False)  # 0=dry, 1=wet, 2=flooded

    def get_appearance(self, tile: "Tile", surface_water: int = 0) -> object:
        """Get cached appearance, computing if needed.

        Args:
            tile: Parent tile (for terrain data if no override)
            surface_water: Current water level (passed in as it's now external)

        Returns:
            SurfaceAppearance instance
        """
        if self._cached_appearance is None:
            from surface_state import compute_surface_appearance
            self._cached_appearance = compute_surface_appearance(self, tile, surface_water)
        return self._cached_appearance

    def invalidate_appearance(self) -> None:
        """Mark appearance cache as stale. Will be recomputed on next access."""
        self._cached_appearance = None

    def check_water_threshold(self, current_water: int) -> bool:
        """Check if water crossed a visual threshold, invalidating if so.

        Returns:
            True if appearance was invalidated
        """
        # Determine current water state
        if current_water > 50:
            new_state = 2  # flooded
        elif current_water > 5:
            new_state = 1  # wet
        else:
            new_state = 0  # dry

        if new_state != self._last_water_state:
            self._last_water_state = new_state
            self.invalidate_appearance()
            return True
        return False


# =============================================================================
# Coordinate Conversion Utilities
# =============================================================================

def tile_to_subgrid(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Convert tile coords to top-left sub-square coords.

    Example: tile (2, 3) -> sub-square (6, 9)
    """
    return tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE


def subgrid_to_tile(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Convert sub-square coords to containing tile coords.

    Example: sub-square (7, 10) -> tile (2, 3)
    """
    return sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE


def get_subsquare_index(sub_x: int, sub_y: int) -> Tuple[int, int]:
    """Get index within tile (0-2, 0-2) from world sub-coords.

    Example: sub-square (7, 10) -> index (1, 1) within its tile
    """
    return sub_x % SUBGRID_SIZE, sub_y % SUBGRID_SIZE


def tile_center_subsquare(tile_x: int, tile_y: int) -> Tuple[int, int]:
    """Get the center sub-square coords for a tile.

    Example: tile (2, 3) -> sub-square (7, 10) (center of 3x3)
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
    return player_pos[0] + dx, player_pos[1] + dy


def clamp_to_bounds(pos: Tuple[int, int], width: int, height: int) -> Tuple[int, int]:
    """Clamp position to within map bounds.

    Args:
        pos: Position to clamp
        width: Map width in sub-squares
        height: Map height in sub-squares

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
    """Get neighboring sub-square coords in given direction.

    Args:
        sub_x, sub_y: Current sub-square world coords
        direction: (dx, dy) offset

    Returns:
        Neighboring sub-square world coords
    """
    return sub_x + direction[0], sub_y + direction[1]


def is_on_range_edge(pos: Tuple[int, int], center: Tuple[int, int],
                     interaction_range: int) -> bool:
    """Check if position is on the edge of the interaction range.

    Used for rendering range boundary indicators.
    """
    dist = chebyshev_distance(pos, center)
    return dist == interaction_range


# =============================================================================
# Terrain Access Utilities
# =============================================================================

def get_subsquare_terrain(subsquare: SubSquare, tile_terrain: "TerrainColumn") -> "TerrainColumn":
    """Get the effective terrain for a sub-square.

    Returns the sub-square's terrain_override if it has one,
    otherwise returns the parent tile's terrain.

    Args:
        subsquare: The sub-square to get terrain for
        tile_terrain: The parent tile's terrain (fallback)

    Returns:
        The effective TerrainColumn for this sub-square
    """
    if subsquare.terrain_override is not None:
        return subsquare.terrain_override
    return tile_terrain


