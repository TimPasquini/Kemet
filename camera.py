# camera.py
"""
Camera system for viewport management.

Handles the transformation between four coordinate spaces:
1. World space - pixel coordinates in the game world
2. Tile space - coarse grid coordinates (simulation level)
3. Sub-grid space - fine grid coordinates (3x tile resolution)
4. Viewport space - coordinates within the visible map area

The camera tracks a position in world space and defines what portion
of the world is visible in the viewport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional

from config import SUBGRID_SIZE


@dataclass
class Camera:
    """
    Manages the viewport into the game world.

    The camera position represents the world coordinates at the center
    of the viewport (or top-left, configurable).
    """
    # World position (top-left of viewport in world pixels)
    world_x: float = 0.0
    world_y: float = 0.0

    # Viewport size in world pixels (how much of the world is visible)
    viewport_width: int = 640
    viewport_height: int = 480

    # World bounds (for clamping camera position)
    world_pixel_width: int = 1280
    world_pixel_height: int = 960

    # Tile size for coordinate conversions
    tile_size: int = 32

    def set_world_bounds(self, world_width_tiles: int, world_height_tiles: int, tile_size: int) -> None:
        """Set the world bounds based on tile dimensions."""
        self.world_pixel_width = world_width_tiles * tile_size
        self.world_pixel_height = world_height_tiles * tile_size
        self.tile_size = tile_size

    def set_viewport_size(self, width: int, height: int) -> None:
        """Set the viewport size in pixels."""
        self.viewport_width = width
        self.viewport_height = height

    def center_on(self, world_x: float, world_y: float) -> None:
        """Center the camera on a world position."""
        self.world_x = world_x - self.viewport_width / 2
        self.world_y = world_y - self.viewport_height / 2
        self._clamp_to_bounds()

    def center_on_tile(self, tile_x: int, tile_y: int) -> None:
        """Center the camera on a tile."""
        world_x = tile_x * self.tile_size + self.tile_size / 2
        world_y = tile_y * self.tile_size + self.tile_size / 2
        self.center_on(world_x, world_y)

    def follow(self, world_x: float, world_y: float, margin: float = 0.3) -> None:
        """
        Smoothly follow a position, only moving when target is near edge.

        margin: fraction of viewport size to use as dead zone (0.3 = 30%)
        """
        margin_x = self.viewport_width * margin
        margin_y = self.viewport_height * margin

        # Calculate target position in viewport space
        vx = world_x - self.world_x
        vy = world_y - self.world_y

        # Only adjust if outside the margin
        if vx < margin_x:
            self.world_x = world_x - margin_x
        elif vx > self.viewport_width - margin_x:
            self.world_x = world_x - (self.viewport_width - margin_x)

        if vy < margin_y:
            self.world_y = world_y - margin_y
        elif vy > self.viewport_height - margin_y:
            self.world_y = world_y - (self.viewport_height - margin_y)

        self._clamp_to_bounds()

    def _clamp_to_bounds(self) -> None:
        """Clamp camera position to world bounds."""
        max_x = max(0, self.world_pixel_width - self.viewport_width)
        max_y = max(0, self.world_pixel_height - self.viewport_height)

        self.world_x = max(0, min(self.world_x, max_x))
        self.world_y = max(0, min(self.world_y, max_y))

    def world_to_viewport(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """Convert world coordinates to viewport coordinates."""
        return (world_x - self.world_x, world_y - self.world_y)

    def viewport_to_world(self, vp_x: float, vp_y: float) -> Tuple[float, float]:
        """Convert viewport coordinates to world coordinates."""
        return (vp_x + self.world_x, vp_y + self.world_y)

    def world_to_tile(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """Convert world pixel coordinates to tile coordinates."""
        return (int(world_x // self.tile_size), int(world_y // self.tile_size))

    def tile_to_world(self, tile_x: int, tile_y: int) -> Tuple[float, float]:
        """Convert tile coordinates to world pixel coordinates (top-left of tile)."""
        return (tile_x * self.tile_size, tile_y * self.tile_size)

    # =========================================================================
    # Sub-grid coordinate conversions
    # =========================================================================

    @property
    def sub_tile_size(self) -> float:
        """Size of a sub-square in world pixels."""
        return self.tile_size / SUBGRID_SIZE

    def world_to_subsquare(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """Convert world pixel coordinates to sub-grid coordinates."""
        sub_size = self.sub_tile_size
        return (int(world_x // sub_size), int(world_y // sub_size))

    def subsquare_to_world(self, sub_x: int, sub_y: int) -> Tuple[float, float]:
        """Convert sub-grid coordinates to world pixel coordinates (top-left of sub-square)."""
        sub_size = self.sub_tile_size
        return (sub_x * sub_size, sub_y * sub_size)

    def subsquare_to_world_center(self, sub_x: int, sub_y: int) -> Tuple[float, float]:
        """Convert sub-grid coordinates to world pixel coordinates (center of sub-square)."""
        sub_size = self.sub_tile_size
        return (sub_x * sub_size + sub_size / 2, sub_y * sub_size + sub_size / 2)

    def subsquare_to_tile(self, sub_x: int, sub_y: int) -> Tuple[int, int]:
        """Convert sub-grid coordinates to tile coordinates."""
        return (sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE)

    def tile_to_subsquare(self, tile_x: int, tile_y: int) -> Tuple[int, int]:
        """Convert tile coordinates to sub-grid coordinates (top-left of tile)."""
        return (tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE)

    def get_visible_subsquare_range(self) -> Tuple[int, int, int, int]:
        """
        Get the range of sub-squares visible in the viewport.

        Returns: (start_x, start_y, end_x, end_y) - end is exclusive
        """
        sub_size = self.sub_tile_size
        world_sub_width = (self.world_pixel_width // self.tile_size) * SUBGRID_SIZE
        world_sub_height = (self.world_pixel_height // self.tile_size) * SUBGRID_SIZE

        start_x = max(0, int(self.world_x // sub_size))
        start_y = max(0, int(self.world_y // sub_size))

        end_x = min(
            int((self.world_x + self.viewport_width) // sub_size) + 1,
            world_sub_width
        )
        end_y = min(
            int((self.world_y + self.viewport_height) // sub_size) + 1,
            world_sub_height
        )

        return (start_x, start_y, end_x, end_y)

    def is_subsquare_visible(self, sub_x: int, sub_y: int) -> bool:
        """Check if a sub-square is within the visible viewport."""
        start_x, start_y, end_x, end_y = self.get_visible_subsquare_range()
        return start_x <= sub_x < end_x and start_y <= sub_y < end_y

    def get_visible_tile_range(self) -> Tuple[int, int, int, int]:
        """
        Get the range of tiles visible in the viewport.

        Returns: (start_x, start_y, end_x, end_y) - end is exclusive
        """
        start_x = max(0, int(self.world_x // self.tile_size))
        start_y = max(0, int(self.world_y // self.tile_size))

        # Calculate end tiles (add 1 for partial tiles at edge)
        end_x = min(
            int((self.world_x + self.viewport_width) // self.tile_size) + 1,
            self.world_pixel_width // self.tile_size
        )
        end_y = min(
            int((self.world_y + self.viewport_height) // self.tile_size) + 1,
            self.world_pixel_height // self.tile_size
        )

        return (start_x, start_y, end_x, end_y)

    def is_tile_visible(self, tile_x: int, tile_y: int) -> bool:
        """Check if a tile is within the visible viewport."""
        start_x, start_y, end_x, end_y = self.get_visible_tile_range()
        return start_x <= tile_x < end_x and start_y <= tile_y < end_y

    def is_world_pos_visible(self, world_x: float, world_y: float) -> bool:
        """Check if a world position is within the visible viewport."""
        vp_x, vp_y = self.world_to_viewport(world_x, world_y)
        return 0 <= vp_x < self.viewport_width and 0 <= vp_y < self.viewport_height
