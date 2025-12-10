# player.py
"""
Player state management for Kemet.

Handles:
- Player position (in sub-grid coordinates)
- Action timer system (for timed actions)
- Smooth movement with sub-pixel precision

Coordinate Systems:
- Sub-grid coords (int): Player's discrete position for game logic
- Sub-grid coords (float): Smooth position for rendering
- Tile coords: Coarse position for simulation interaction (derived)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from config import ACTION_DURATIONS, DIAGONAL_FACTOR, SUBGRID_SIZE, SUB_TILE_SIZE
from subgrid import subgrid_to_tile
from utils import clamp

Point = Tuple[int, int]


@dataclass
class PlayerState:
    """
    Player state including position and action timing.

    Position is stored in sub-grid coordinates with sub-pixel precision.
    The integer position is used for game logic, float for smooth rendering.
    """
    # Smooth position in sub-grid units (float for smooth movement)
    smooth_x: float = 0.0
    smooth_y: float = 0.0

    action_timer: float = 0.0
    last_action: str = ""
    last_rock_blocked: Point | None = None  # Tile coordinates

    @property
    def position(self) -> Point:
        """Get discrete sub-grid position for game logic."""
        return (int(self.smooth_x), int(self.smooth_y))

    @position.setter
    def position(self, value: Point) -> None:
        """Set position (centers player in sub-square)."""
        self.smooth_x = float(value[0]) + 0.5
        self.smooth_y = float(value[1]) + 0.5

    @property
    def tile_position(self) -> Point:
        """Get the tile coordinates containing the player."""
        return subgrid_to_tile(int(self.smooth_x), int(self.smooth_y))

    @property
    def subsquare_index(self) -> Point:
        """Get the local subsquare index (0-2, 0-2) within the current tile."""
        return (int(self.smooth_x) % SUBGRID_SIZE, int(self.smooth_y) % SUBGRID_SIZE)

    @property
    def world_pixel_pos(self) -> Tuple[float, float]:
        """Get world position in pixels for rendering."""
        return (self.smooth_x * SUB_TILE_SIZE, self.smooth_y * SUB_TILE_SIZE)

    def start_action(self, action: str) -> bool:
        """Start an action if not busy."""
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
        """Get progress of current action (0.0 to 1.0)."""
        if self.action_timer <= 0:
            return 0.0
        duration = ACTION_DURATIONS.get(self.last_action, 1.0)
        return self.action_timer / duration


def update_player_movement(
    player_state: PlayerState,
    velocity: Tuple[float, float],
    dt: float,
    world_width_subsquares: int,
    world_height_subsquares: int,
    is_tile_blocked: callable,
) -> None:
    """
    Update player position based on velocity and collision.

    Movement is in sub-grid space. Velocity is in sub-squares per second.
    Collision checking occurs at tile level.

    Args:
        player_state: The player state to update
        velocity: (vx, vy) velocity in sub-squares per second
        dt: Delta time in seconds
        world_width_subsquares: World width in sub-squares
        world_height_subsquares: World height in sub-squares
        is_tile_blocked: Function(tile_x, tile_y) -> bool
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

    # Calculate new position in sub-grid space
    new_x = player_state.smooth_x + vx * dt
    new_y = player_state.smooth_y + vy * dt

    # Clamp to world bounds
    new_x = clamp(new_x, 0.5, world_width_subsquares - 0.5)
    new_y = clamp(new_y, 0.5, world_height_subsquares - 0.5)

    # Get target tile for collision check
    target_tile = subgrid_to_tile(int(new_x), int(new_y))
    current_tile = player_state.tile_position

    # Check for collision at tile level
    if is_tile_blocked(target_tile[0], target_tile[1]):
        if target_tile != current_tile:
            if target_tile != player_state.last_rock_blocked:
                player_state.last_rock_blocked = target_tile
            return

    # Update smooth position
    player_state.smooth_x = new_x
    player_state.smooth_y = new_y
