# player.py
"""
Player state management for Kemet.

Handles:
- Player position
- Action timer system (for timed actions)
- Movement state tracking
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from config import ACTION_DURATIONS

Point = Tuple[int, int]


@dataclass
class PlayerState:
    """
    Player state including position and action timing.

    The action timer system handles timed actions like digging,
    building, etc. When an action starts, the timer is set to
    the action's duration and counts down.
    """
    position: Point = (0, 0)
    action_timer: float = 0.0
    last_action: str = ""
    last_rock_blocked: Point | None = None

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
