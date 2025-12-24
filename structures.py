# structures.py
"""
structures.py - Player-built structures for Kemet

Defines structure types, costs, and behavior:
- Depot: Player's starting base/storage location
- Cistern: Stores water, reduces evaporation
- Condenser: Generates water from air
- Planter: Grows biomass when watered

All structures operate on grid coordinates (sx, sy for grid cells, tx, ty for tile coords).
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

from ground import SoilLayer
from config import (
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
from simulation.surface import (
    get_tile_surface_water,
    distribute_upward_seepage,
    remove_water_proportionally,
)
from subgrid import subgrid_to_tile

if TYPE_CHECKING:
    from main import GameState, Inventory


@dataclass
class Structure(ABC):
    """Represents a player-built structure on a grid cell.

    Structures are placed at grid cell coordinates (sx, sy) and can affect
    the parent tile (tx, ty) or surrounding cells.
    """
    kind: str
    hp: int = 3

    @abstractmethod
    def tick(self, state: "GameState", tx: int, ty: int, sx: int, sy: int) -> None:
        """Update the structure for one simulation tick.

        Args:
            state: GameState with all grid data
            tx, ty: Parent tile coordinates
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

    def tick(self, state: "GameState", tx: int, ty: int, sx: int, sy: int) -> None:
        # Depot is passive - no tick behavior needed
        pass

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Condenser(Structure):
    """Generates water from the air."""
    kind: str = "condenser"

    def tick(self, state: "GameState", tx: int, ty: int, sx: int, sy: int) -> None:
        # Add water to grid cells (distributed by elevation)
        distribute_upward_seepage(CONDENSER_OUTPUT, state.active_water_subsquares, tx, ty, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Cistern(Structure):
    """Stores surface water from the parent tile."""
    kind: str = "cistern"
    stored: int = 0  # Water storage in units

    def tick(self, state: "GameState", tx: int, ty: int, sx: int, sy: int) -> None:
        # Get total surface water from parent tile's grid cells
        surface_water = get_tile_surface_water(state.water_grid, tx, ty)

        # Transfer surface water into cistern storage
        if surface_water > CISTERN_TRANSFER_RATE and self.stored < CISTERN_CAPACITY:
            transfer = min(CISTERN_TRANSFER_RATE, surface_water, CISTERN_CAPACITY - self.stored)
            # Remove water proportionally from grid cells
            remove_water_proportionally(transfer, state, tx, ty)
            self.stored += transfer

        # Cistern slowly leaks (scales with heat)
        loss = (CISTERN_LOSS_RATE * state.heat) // 100
        drained = min(self.stored, loss)
        self.stored -= drained
        recovered = (drained * CISTERN_LOSS_RECOVERY) // 100
        distribute_upward_seepage(recovered, state.active_water_subsquares, tx, ty, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind} | stored={self.stored / 10:.1f}L"

    def get_status_summary(self) -> Dict[str, int]:
        return {"stored_water": self.stored}


@dataclass
class Planter(Structure):
    """Grows biomass when watered, adds organic matter to soil."""
    kind: str = "planter"
    growth: int = 0  # Growth progress 0-100

    def tick(self, state: "GameState", tx: int, ty: int, sx: int, sy: int) -> None:
        # Total water includes grid cell surface water + subsurface (from grids)
        from grid_helpers import get_tile_total_water
        total_water = get_tile_total_water(state, tx, ty)

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
            remove_water_proportionally(PLANTER_WATER_COST, state, tx, ty)
            
            # Update Array (Source of Truth)
            current_depth = state.terrain_layers[SoilLayer.ORGANICS, sx, sy]
            if current_depth < MAX_ORGANICS_DEPTH:
                state.terrain_layers[SoilLayer.ORGANICS, sx, sy] += 1
                if not state.terrain_materials[SoilLayer.ORGANICS, sx, sy]:
                    state.terrain_materials[SoilLayer.ORGANICS, sx, sy] = "humus"
                state.terrain_changed = True
                state.dirty_subsquares.add((sx, sy))
            state.messages.append(f"Biomass harvested! (Total {state.inventory.biomass})")

    def get_survey_string(self) -> str:
        return f"struct={self.kind} | growth={self.growth}%"


def build_structure(state: "GameState", kind: str) -> None:
    """Build a structure at target sub-square."""
    from subgrid import subgrid_to_tile, get_subsquare_index

    kind = kind.lower()
    if kind not in STRUCTURE_COSTS:
        state.messages.append("Cannot build that.")
        return

    # Get sub-square position for structure placement
    sub_pos = state.get_action_target_subsquare()
    tile_pos = subgrid_to_tile(sub_pos[0], sub_pos[1])

    # Validate build location
    if sub_pos in state.structures:
        state.messages.append("Already has a structure here.")
        return
    if state.get_tile_kind(tile_pos[0], tile_pos[1]) == "rock":
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
    state.structures[sub_pos] = structure_class_map[kind]()

    # Update cistern cache for evaporation optimization
    if kind == "cistern":
        state.register_cistern(tile_pos[0], tile_pos[1])

    state.messages.append(f"Built {kind} at sub-square {sub_pos}.")


def tick_structures(state: "GameState", heat: int) -> None:
    """Update all structures for one simulation tick.

    Structures are keyed by grid cell coords (sx, sy) but their effects
    (water collection, growth) can affect the parent tile (tx, ty).
    """
    from subgrid import subgrid_to_tile

    for sub_pos, structure in list(state.structures.items()):
        # Get parent tile coordinates for this structure's grid cell
        tile_pos = subgrid_to_tile(sub_pos[0], sub_pos[1])
        structure.tick(state, tile_pos[0], tile_pos[1], sub_pos[0], sub_pos[1])
