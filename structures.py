# structures.py
"""
structures.py - Player-built structures for Kemet

Defines structure types, costs, and behavior:
- Depot: Player's starting base/storage location
- Cistern: Stores water, reduces evaporation
- Condenser: Generates water from air
- Planter: Grows biomass when watered

All structures operate on grid cell coordinates (sx, sy).
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

from world.terrain import SoilLayer
from core.config import (
    CONDENSER_OUTPUT,
    PLANTER_GROWTH_RATE,
    PLANTER_GROWTH_THRESHOLD,
    PLANTER_WATER_COST,
    PLANTER_WATER_REQUIREMENT,
    MAX_ORGANICS_DEPTH,
    CISTERN_CAPACITY,
    CISTERN_TRANSFER_RATE,
    CISTERN_LOSS_RATE,
    CISTERN_LOSS_RECOVERY,
    STRUCTURE_COSTS,
)
from simulation.surface import distribute_upward_seepage, remove_water_from_cell_neighborhood
from core.grid_helpers import get_cell_neighborhood_surface_water, get_cell_neighborhood_total_water

if TYPE_CHECKING:
    from main import GameState, Inventory


@dataclass
class Structure(ABC):
    """Represents a player-built structure on a grid cell.

    Structures are placed at grid cell coordinates (sx, sy) and affect
    their own cell or neighboring cells.
    """
    kind: str
    hp: int = 3

    @abstractmethod
    def tick(self, state: "GameState", sx: int, sy: int) -> None:
        """Update the structure for one simulation tick.

        Args:
            state: GameState with all grid data
            sx, sy: Grid cell coordinates where structure is placed
        """
        pass

    @abstractmethod
    def get_survey_string(self) -> str:
        """Return a string with the structure's status for the survey command."""
        pass

    def get_status_summary(self) -> Optional[Dict[str, int]]:
        """Return a dict of values for the global status report, or None."""
        return None


@dataclass
class Depot(Structure):
    """Player's starting base/storage location."""
    kind: str = "depot"

    def tick(self, state: "GameState", sx: int, sy: int) -> None:
        # Depot is passive - no tick behavior needed
        pass

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Condenser(Structure):
    """Generates water from the air."""
    kind: str = "condenser"

    def tick(self, state: "GameState", sx: int, sy: int) -> None:
        # Add water to grid cell neighborhood (distributed by elevation)
        distribute_upward_seepage(CONDENSER_OUTPUT, state.active_water_cells, sx, sy, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Cistern(Structure):
    """Stores surface water from surrounding grid cells."""
    kind: str = "cistern"
    stored: int = 0  # Water storage in units

    def tick(self, state: "GameState", sx: int, sy: int) -> None:
        # Get total surface water from cell neighborhood
        surface_water = get_cell_neighborhood_surface_water(state, sx, sy)

        # Transfer surface water into cistern storage
        if surface_water > CISTERN_TRANSFER_RATE and self.stored < CISTERN_CAPACITY:
            transfer = min(CISTERN_TRANSFER_RATE, surface_water, CISTERN_CAPACITY - self.stored)
            # Remove water proportionally from grid cell neighborhood
            remove_water_from_cell_neighborhood(transfer, state, sx, sy)
            self.stored += transfer

        # Cistern slowly leaks (scales with heat)
        loss = (CISTERN_LOSS_RATE * state.heat) // 100
        drained = min(self.stored, loss)
        self.stored -= drained
        recovered = (drained * CISTERN_LOSS_RECOVERY) // 100
        distribute_upward_seepage(recovered, state.active_water_cells, sx, sy, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind} | stored={self.stored / 10:.1f}L"

    def get_status_summary(self) -> Dict[str, int]:
        return {"stored_water": self.stored}


@dataclass
class Planter(Structure):
    """Grows biomass when watered, adds organic matter to soil."""
    kind: str = "planter"
    growth: int = 0  # Growth progress 0-100

    def tick(self, state: "GameState", sx: int, sy: int) -> None:
        # Total water includes grid cell neighborhood surface water + subsurface
        total_water = get_cell_neighborhood_total_water(state, sx, sy)

        if total_water >= PLANTER_WATER_REQUIREMENT:
            self.growth += PLANTER_GROWTH_RATE
            if self.growth > PLANTER_GROWTH_THRESHOLD:
                self.growth = PLANTER_GROWTH_THRESHOLD
        else:
            self.growth = max(self.growth - 10, 0)

        if self.growth >= PLANTER_GROWTH_THRESHOLD:
            self.growth = 0
            state.inventory.biomass += 1
            state.inventory.seeds += 1
            remove_water_from_cell_neighborhood(PLANTER_WATER_COST, state, sx, sy)

            # Update Array (Source of Truth)
            current_depth = state.terrain_layers[SoilLayer.ORGANICS, sx, sy]
            if current_depth < MAX_ORGANICS_DEPTH:
                state.terrain_layers[SoilLayer.ORGANICS, sx, sy] += 1
                if not state.terrain_materials[SoilLayer.ORGANICS, sx, sy]:
                    state.terrain_materials[SoilLayer.ORGANICS, sx, sy] = "humus"
                state.terrain_changed = True
                state.dirty_cells.add((sx, sy))
            state.messages.append(f"Biomass harvested! (Total {state.inventory.biomass})")

    def get_survey_string(self) -> str:
        return f"struct={self.kind} | growth={self.growth}%"


def build_structure(state: "GameState", kind: str) -> None:
    """Build a structure at target grid cell."""
    
    kind = kind.lower()
    if kind not in STRUCTURE_COSTS:
        state.messages.append("Cannot build that.")
        return

    # Get grid cell position for structure placement
    cell_pos = state.get_action_target_cell()
    sx, sy = cell_pos

    # Validate build location
    if cell_pos in state.structures:
        state.messages.append("Already has a structure here.")
        return
    if state.get_cell_kind(sx, sy) == "rock":
        state.messages.append("Cannot build on rock.")
        return

    cost = STRUCTURE_COSTS[kind]
    if state.inventory.scrap < cost.get("scrap", 0):
        state.messages.append(f"Need {cost.get('scrap', 0)} scrap to build {kind}.")
        return
    if state.inventory.seeds < cost.get("seeds", 0):
        state.messages.append(f"Need {cost.get('seeds', 0)} seeds to build {kind}.")
        return

    state.inventory.scrap -= cost.get("scrap", 0)
    state.inventory.seeds -= cost.get("seeds", 0)

    structure_class_map = {
        "depot": Depot,
        "condenser": Condenser,
        "cistern": Cistern,
        "planter": Planter,
    }
    state.structures[cell_pos] = structure_class_map[kind]()

    # Update cistern cache for evaporation optimization
    if kind == "cistern":
        state.register_cistern(sx, sy)

    state.messages.append(f"Built {kind} at grid cell {cell_pos}.")


def tick_structures(state: "GameState", heat: int) -> None:
    """Update all structures for one simulation tick.

    Structures are keyed by grid cell coords (sx, sy) and affect their
    cell and neighboring cells (3×3 neighborhood).
    """
    # Direct iteration without list() conversion - structures dict is not modified during tick
    for cell_pos, structure in state.structures.items():
        structure.tick(state, cell_pos[0], cell_pos[1])
