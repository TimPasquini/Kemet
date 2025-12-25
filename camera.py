# camera.py
"""
Camera system for viewport management.

Handles the transformation between three coordinate spaces:
1. World space - pixel coordinates in the game world
2. Grid space - grid cell coordinates (180×135 cells)
3. Viewport space - coordinates within the visible map area

The camera tracks a position in world space and defines what portion
of the world is visible in the viewport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


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

    # Grid cell size for coordinate conversions
    tile_size: int = 32  # Note: legacy name, represents cell_size * 3

    # Zoom level (1.0 = 100%, 0.5 = 50% size / 2x view area, 2.0 = 200% size)
    zoom: float = 1.0

    def set_world_bounds(self, world_width_cells: int, world_height_cells: int, cell_size: int) -> None:
        """Set the world bounds based on grid cell dimensions.

        Args:
            world_width_cells: Width of world in grid cells (e.g., GRID_WIDTH = 180)
            world_height_cells: Height of world in grid cells (e.g., GRID_HEIGHT = 135)
            cell_size: Size of each grid cell in pixels (e.g., SUB_TILE_SIZE = 48)
        """
        self.world_pixel_width = world_width_cells * cell_size
        self.world_pixel_height = world_height_cells * cell_size
        self.tile_size = cell_size  # Note: legacy name 'tile_size', represents cell_size * 3 grouping

    def set_viewport_size(self, width: int, height: int) -> None:
        """Set the viewport size in pixels."""
        self.viewport_width = width
        self.viewport_height = height

    def set_zoom(self, zoom_level: float) -> None:
        """Set zoom level, clamping to reasonable bounds."""
        self.zoom = max(0.25, min(4.0, zoom_level))
        self._clamp_to_bounds()

    def center_on(self, world_x: float, world_y: float) -> None:
        """Center the camera on a world position."""
        self.world_x = world_x - (self.viewport_width / self.zoom) / 2
        self.world_y = world_y - (self.viewport_height / self.zoom) / 2
        self._clamp_to_bounds()

    def follow(self, world_x: float, world_y: float, margin: float = 0.3) -> None:
        """
        Smoothly follow a position, only moving when target is near edge.

        margin: fraction of viewport size to use as dead zone (0.3 = 30%)
        """
        margin_x = self.viewport_width * margin
        margin_y = self.viewport_height * margin
        
        # Viewport extent in world units depends on zoom
        view_w_world = self.viewport_width / self.zoom
        view_h_world = self.viewport_height / self.zoom

        # Calculate target position relative to camera
        vx = world_x - self.world_x
        vy = world_y - self.world_y

        # Margin in world units (approximate for smooth feel)
        world_margin_x = margin_x / self.zoom
        world_margin_y = margin_y / self.zoom

        if vx < world_margin_x:
            self.world_x = world_x - world_margin_x
        elif vx > view_w_world - world_margin_x:
            self.world_x = world_x - (view_w_world - world_margin_x)

        if vy < world_margin_y:
            self.world_y = world_y - world_margin_y
        elif vy > view_h_world - world_margin_y:
            self.world_y = world_y - (view_h_world - world_margin_y)

        self._clamp_to_bounds()

    def _clamp_to_bounds(self) -> None:
        """Clamp camera position to world bounds."""
        # Visible world width/height
        visible_w = self.viewport_width / self.zoom
        visible_h = self.viewport_height / self.zoom
        
        max_x = max(0, self.world_pixel_width - visible_w)
        max_y = max(0, self.world_pixel_height - visible_h)

        self.world_x = max(0, min(self.world_x, max_x))
        self.world_y = max(0, min(self.world_y, max_y))

    def world_to_viewport(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """Convert world coordinates to viewport coordinates."""
        return (world_x - self.world_x) * self.zoom, (world_y - self.world_y) * self.zoom

    def viewport_to_world(self, vp_x: float, vp_y: float) -> Tuple[float, float]:
        """Convert viewport coordinates to world coordinates."""
        return (vp_x / self.zoom) + self.world_x, (vp_y / self.zoom) + self.world_y


    # =========================================================================
    # Sub-grid coordinate conversions
    # =========================================================================

    @property
    def sub_tile_size(self) -> float:
        """Size of a grid cell in world pixels."""
        return self.tile_size / 3

    def world_to_subsquare(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """Convert world pixel coordinates to grid cell coordinates."""
        sub_size = self.sub_tile_size
        return int(world_x // sub_size), int(world_y // sub_size)

    def subsquare_to_world(self, sub_x: int, sub_y: int) -> Tuple[float, float]:
        """Convert grid cell coordinates to world pixel coordinates (top-left of cell)."""
        sub_size = self.sub_tile_size
        return sub_x * sub_size, sub_y * sub_size

    def subsquare_to_world_center(self, sub_x: int, sub_y: int) -> Tuple[float, float]:
        """Convert grid cell coordinates to world pixel coordinates (center of cell)."""
        sub_size = self.sub_tile_size
        return sub_x * sub_size + sub_size / 2, sub_y * sub_size + sub_size / 2


    def get_visible_subsquare_range(self) -> Tuple[int, int, int, int]:
        """
        Get the range of grid cells visible in the viewport.

        Returns: (start_x, start_y, end_x, end_y) - end is exclusive
        """
        sub_size = self.sub_tile_size
        # Calculate world dimensions in grid cells directly from pixel dimensions
        world_sub_width = int(self.world_pixel_width // sub_size)
        world_sub_height = int(self.world_pixel_height // sub_size)

        start_x = max(0, int(self.world_x // sub_size))
        start_y = max(0, int(self.world_y // sub_size))

        end_x = min(
            int((self.world_x + (self.viewport_width / self.zoom)) // sub_size) + 1,
            world_sub_width
        )
        end_y = min(
            int((self.world_y + (self.viewport_height / self.zoom)) // sub_size) + 1,
            world_sub_height
        )

        return start_x, start_y, end_x, end_y

    def is_subsquare_visible(self, sub_x: int, sub_y: int) -> bool:
        """Check if a grid cell is within the visible viewport."""
        start_x, start_y, end_x, end_y = self.get_visible_subsquare_range()
        return start_x <= sub_x < end_x and start_y <= sub_y < end_y


    def is_world_pos_visible(self, world_x: float, world_y: float) -> bool:
        """Check if a world position is within the visible viewport."""
        vp_x, vp_y = self.world_to_viewport(world_x, world_y)
        return 0 <= vp_x < self.viewport_width and 0 <= vp_y < self.viewport_height
