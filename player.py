# player.py
"""
Player state management for Kemet.

Handles:
- Player position (in sub-grid coordinates)
- Action timer system (for timed actions)
- Movement state tracking

Coordinate Systems:
- Sub-grid coords: Fine-grained position (3x per tile dimension)
- Tile coords: Coarse position for simulation interaction
- World pixel coords: Rendering position
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from config import ACTION_DURATIONS, DIAGONAL_FACTOR, SUBGRID_SIZE
from subgrid import subgrid_to_tile, tile_center_subsquare
from utils import clamp

Point = Tuple[int, int]


@dataclass
class PlayerState:
    """
    Player state including position and action timing.

    Position is stored in sub-grid coordinates (3x resolution of tiles).
    Use tile_position property to get the containing tile coordinates.

    The action timer system handles timed actions like digging,
    building, etc. When an action starts, the timer is set to
    the action's duration and counts down.
    """
    position: Point = (0, 0)  # Sub-grid coordinates
    action_timer: float = 0.0
    last_action: str = ""
    last_rock_blocked: Point | None = None  # Tile coordinates

    @property
    def tile_position(self) -> Point:
        """Get the tile coordinates containing the player."""
        return subgrid_to_tile(self.position[0], self.position[1])

    @property
    def subsquare_index(self) -> Point:
        """Get the local subsquare index (0-2, 0-2) within the current tile."""
        return (self.position[0] % SUBGRID_SIZE, self.position[1] % SUBGRID_SIZE)

    def start_action(self, action: str) -> bool:
        """
        Start an action if not busy.

        Args:
            action: Action name (must be in ACTION_DURATIONS)

        Returns:
            True if action started, False if already busy
        """
        if self.action_timer > 0:
            return False
        duration = ACTION_DURATIONS.get(action, 0)
        if duration > 0:
            self.action_timer = duration
            self.last_action = action
        return True

    def update_action_timer(self, dt: float) -> None:
        """Update action timer by delta time in seconds."""
        if self.action_timer > 0:
            self.action_timer = max(0.0, self.action_timer - dt)

    def is_busy(self) -> bool:
        """Check if player is currently performing an action."""
        return self.action_timer > 0

    def get_action_progress(self) -> float:
        """
        Get progress of current action.

        Returns:
            Float from 0.0 (just started) to 1.0 (almost done).
            Returns 0.0 if no action in progress.
        """
        if self.action_timer <= 0:
            return 0.0
        duration = ACTION_DURATIONS.get(self.last_action, 1.0)
        return self.action_timer / duration


def update_player_movement(
    player_state: PlayerState,
    world_pos: list[float],
    velocity: Tuple[float, float],
    dt: float,
    tile_size: int,
    world_width_tiles: int,
    world_height_tiles: int,
    is_tile_blocked: callable,
) -> None:
    """
    Update player position based on velocity and collision.

    Player position is tracked at sub-grid resolution (3x tiles).
    Collision checking still occurs at tile level.

    Args:
        player_state: The player state to update
        world_pos: [x, y] world position in pixels (mutable, will be updated)
        velocity: (vx, vy) velocity in pixels per second
        dt: Delta time in seconds
        tile_size: Size of tiles in pixels
        world_width_tiles: World width in tiles
        world_height_tiles: World height in tiles
        is_tile_blocked: Function(tile_x, tile_y) -> bool to check if tile blocks movement
    """
    if player_state.is_busy():
        return

    vx, vy = velocity
    if vx == 0.0 and vy == 0.0:
        return

    # Normalize diagonal movement
    if vx != 0.0 and vy != 0.0:
        vx *= DIAGONAL_FACTOR
        vy *= DIAGONAL_FACTOR

    world_width = world_width_tiles * tile_size
    world_height = world_height_tiles * tile_size

    # Calculate new position in world pixels
    new_x = clamp(world_pos[0] + vx * dt, 0, world_width - 1)
    new_y = clamp(world_pos[1] + vy * dt, 0, world_height - 1)

    # Get target tile for collision check
    target_tile_x = int(new_x // tile_size)
    target_tile_y = int(new_y // tile_size)

    # Check for collision at tile level
    if is_tile_blocked(target_tile_x, target_tile_y):
        current_tile_x = int(world_pos[0] // tile_size)
        current_tile_y = int(world_pos[1] // tile_size)
        if (target_tile_x, target_tile_y) != (current_tile_x, current_tile_y):
            # Only set last_rock_blocked if entering a new blocked tile
            if (target_tile_x, target_tile_y) != player_state.last_rock_blocked:
                player_state.last_rock_blocked = (target_tile_x, target_tile_y)
            return

    # Update world position
    world_pos[0], world_pos[1] = new_x, new_y

    # Calculate sub-grid position from world pixels
    # Each sub-square is tile_size / SUBGRID_SIZE pixels
    sub_tile_size = tile_size / SUBGRID_SIZE
    sub_x = int(new_x / sub_tile_size)
    sub_y = int(new_y / sub_tile_size)

    # Update player position in sub-grid coordinates
    player_state.position = (sub_x, sub_y)
