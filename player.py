# player.py
"""
Player state management for Kemet.

Handles:
- Player position (in grid cell coordinates)
- Action timer system (for timed actions)
- Smooth movement with sub-pixel precision

Coordinate Systems:
- Grid coords (int): Player's discrete position for game logic (0-179, 0-134)
- Grid coords (float): Smooth position for rendering with sub-pixel precision
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, Callable

from config import ACTION_DURATIONS, DIAGONAL_FACTOR
from utils import clamp

Point = Tuple[int, int]


@dataclass
class PlayerState:
    """
    Player state including position and action timing.

    Position is stored in grid cell coordinates with sub-pixel precision.
    The integer position is used for game logic, float for smooth rendering.
    """
    # Smooth position in grid cell units (float for smooth movement)
    smooth_x: float = 0.0
    smooth_y: float = 0.0

    action_timer: float = 0.0
    last_action: str = ""

    @property
    def position(self) -> Point:
        """Get discrete grid cell position for game logic."""
        return (int(self.smooth_x), int(self.smooth_y))

    @position.setter
    def position(self, value: Point) -> None:
        """Set position (centers player in grid cell)."""
        self.smooth_x = float(value[0]) + 0.5
        self.smooth_y = float(value[1]) + 0.5

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
    world_width_cells: int,
    world_height_cells: int,
    is_cell_blocked: Callable[[int, int], bool],
) -> None:
    """
    Update player position based on velocity and collision.

    Movement is in grid cell space. Velocity is in grid cells per second.
    Collision checking occurs at grid cell level with axis-separated sliding.

    Args:
        player_state: The player state to update
        velocity: (vx, vy) velocity in grid cells per second
        dt: Delta time in seconds
        world_width_cells: World width in grid cells
        world_height_cells: World height in grid cells
        is_cell_blocked: Function(sx, sy) -> bool
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

    current_x = player_state.smooth_x
    current_y = player_state.smooth_y

    # Try X movement first
    new_x = current_x + vx * dt
    new_x = clamp(new_x, 0.5, world_width_cells - 0.5)

    # Check X collision at grid cell level
    new_grid_x = int(new_x)
    current_grid_x = int(current_x)
    if new_grid_x != current_grid_x and is_cell_blocked(new_grid_x, int(current_y)):
        new_x = current_x  # Block X movement
    else:
        current_x = new_x  # Accept X movement

    # Try Y movement (using potentially updated X)
    new_y = current_y + vy * dt
    new_y = clamp(new_y, 0.5, world_height_cells - 0.5)

    # Check Y collision at grid cell level
    new_grid_y = int(new_y)
    current_grid_y = int(current_y)
    if new_grid_y != current_grid_y and is_cell_blocked(int(current_x), new_grid_y):
        new_y = current_y  # Block Y movement

    # Update smooth position
    player_state.smooth_x = current_x
    player_state.smooth_y = new_y
