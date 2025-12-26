# game_state/player_actions.py
"""Player actions for water collection and distribution."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import (
        MAX_POUR_AMOUNT,
    DEPOT_WATER_AMOUNT,
    DEPOT_SCRAP_AMOUNT,
    DEPOT_SEEDS_AMOUNT,
)

if TYPE_CHECKING:
    from game_state.state import GameState


def collect_water(state: GameState) -> None:
    """Collect water from depot or grid cell."""
    # Get target grid cell
    target_cell = state.get_action_target_cell()
    sx, sy = target_cell

    # Check if target cell has a depot structure
    structure = state.structures.get(target_cell)
    if structure and structure.kind == "depot":
        state.inventory.water += DEPOT_WATER_AMOUNT
        state.inventory.scrap += DEPOT_SCRAP_AMOUNT
        state.inventory.seeds += DEPOT_SEEDS_AMOUNT
        state.messages.append(
            f"Depot resupply: +{DEPOT_WATER_AMOUNT / 10:.1f}L water, +{DEPOT_SCRAP_AMOUNT} scrap, +{DEPOT_SEEDS_AMOUNT} seeds.")
        return

    # Otherwise, try to collect water from the grid cell
    available = state.water_grid[sx, sy]

    if available <= 0:
        state.messages.append("No water to collect here.")
        return

    gathered = min(100, available)
    state.water_grid[sx, sy] -= gathered
    state.active_water_cells.add(target_cell)
    state.dirty_cells.add(target_cell)
    state.inventory.water += gathered
    state.messages.append(f"Collected {gathered / 10:.1f}L water.")


def pour_water(state: GameState, amount: float) -> None:
    """Pour water onto grid cell."""
    amount_units = int(amount * 10)
    if not (0 < amount_units <= MAX_POUR_AMOUNT):
        state.messages.append(f"Pour between 0.1L and {MAX_POUR_AMOUNT / 10}L.")
        return
    if state.inventory.water < amount_units:
        state.messages.append("Not enough water carried.")
        return

    target_cell = state.get_action_target_cell()
    sx, sy = target_cell
    state.water_grid[sx, sy] += amount_units

    # Add to active set for flow simulation
    state.active_water_cells.add(target_cell)
    state.dirty_cells.add(target_cell)

    state.inventory.water -= amount_units
    state.messages.append(f"Poured {amount:.1f}L water.")
