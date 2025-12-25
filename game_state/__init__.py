# game_state/__init__.py
"""Game state management module."""

from game_state.state import GameState, Inventory
from game_state.initialization import build_initial_state
from game_state.terrain_actions import (
    dig_trench,
    lower_ground,
    raise_ground,
    terrain_action,
)
from game_state.player_actions import (
    collect_water,
    pour_water,
)

__all__ = [
    'GameState',
    'Inventory',
    'build_initial_state',
    'dig_trench',
    'lower_ground',
    'raise_ground',
    'terrain_action',
    'collect_water',
    'pour_water',
]
