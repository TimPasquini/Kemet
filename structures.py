# structures.py
"""
structures.py - Player-built structures for Kemet

Defines structure types, costs, and behavior:
- Cistern: Stores water, reduces evaporation
- Condenser: Generates water from air
- Planter: Grows biomass when watered
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
    from mapgen import Tile
    from subgrid import SubSquare


@dataclass
class Structure(ABC):
    """Represents a player-built structure on a tile."""
    kind: str
    hp: int = 3

    @abstractmethod
    def tick(self, state: "GameState", tile: "Tile", subsquare: "SubSquare", tx: int, ty: int) -> None:
        """Update the structure for one simulation tick."""
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

    def tick(self, state: "GameState", tile: "Tile", subsquare: "SubSquare", tx: int, ty: int) -> None:
        # Depot is passive - no tick behavior needed
        pass

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Condenser(Structure):
    """Generates water from the air."""
    kind: str = "condenser"

    def tick(self, state: "GameState", tile: "Tile", subsquare: "SubSquare", tx: int, ty: int) -> None:
        # Add water to sub-squares (distributed by elevation)
        distribute_upward_seepage(tile, CONDENSER_OUTPUT, state.active_water_subsquares, tx, ty, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind}"


@dataclass
class Cistern(Structure):
    """Stores surface water."""
    kind: str = "cistern"
    stored: int = 0  # Water storage in units

    def tick(self, state: "GameState", tile: "Tile", subsquare: "SubSquare", tx: int, ty: int) -> None:
        # Get total surface water from sub-squares
        surface_water = get_tile_surface_water(tile, state.water_grid, tx, ty)

        # Transfer surface water into cistern storage
        if surface_water > CISTERN_TRANSFER_RATE and self.stored < CISTERN_CAPACITY:
            transfer = min(CISTERN_TRANSFER_RATE, surface_water, CISTERN_CAPACITY - self.stored)
            # Remove water proportionally from sub-squares
            remove_water_proportionally(tile, transfer, state, tx, ty)
            self.stored += transfer

        # Cistern slowly leaks (scales with heat)
        loss = (CISTERN_LOSS_RATE * state.heat) // 100
        drained = min(self.stored, loss)
        self.stored -= drained
        recovered = (drained * CISTERN_LOSS_RECOVERY) // 100
        distribute_upward_seepage(tile, recovered, state.active_water_subsquares, tx, ty, state)

    def get_survey_string(self) -> str:
        return f"struct={self.kind} | stored={self.stored / 10:.1f}L"

    def get_status_summary(self) -> Dict[str, int]:
        return {"stored_water": self.stored}


@dataclass
class Planter(Structure):
    """Grows biomass when watered."""
    kind: str = "planter"
    growth: int = 0  # Growth progress 0-100

    def tick(self, state: "GameState", tile: "Tile", subsquare: "SubSquare", tx: int, ty: int) -> None:
        from subgrid import ensure_terrain_override  # Local import

        # Total water includes sub-square surface water + subsurface (from grids)
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
            remove_water_proportionally(tile, PLANTER_WATER_COST, state, tx, ty)
            terrain = ensure_terrain_override(subsquare, tile.terrain)
            if terrain.get_layer_depth(SoilLayer.ORGANICS) < MAX_ORGANICS_DEPTH:
                terrain.add_material_to_layer(SoilLayer.ORGANICS, 1)
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
    tile = state.tiles[tile_pos[0]][tile_pos[1]]
    local_x, local_y = get_subsquare_index(sub_pos[0], sub_pos[1])
    subsquare = tile.subgrid[local_x][local_y]

    # Validate build location
    if sub_pos in state.structures:
        state.messages.append("Already has a structure here.")
        return
    if tile.kind == "rock":
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
    subsquare.structure_id = len(state.structures)  # Mark sub-square as having structure

    # Update cistern cache for evaporation optimization
    if kind == "cistern":
        state.register_cistern(tile_pos[0], tile_pos[1])

    state.messages.append(f"Built {kind} at sub-square {sub_pos}.")


def tick_structures(state: "GameState", heat: int) -> None:
    """Update all structures for one simulation tick.

    Structures are keyed by sub-square coords but their effects
    (water collection, growth) operate on the parent tile.
    """
    from subgrid import subgrid_to_tile, get_subsquare_index, ensure_terrain_override

    for sub_pos, structure in list(state.structures.items()):
        # Get parent tile for this structure's sub-square
        tile_pos = subgrid_to_tile(sub_pos[0], sub_pos[1])
        tile = state.tiles[tile_pos[0]][tile_pos[1]]
        local_x, local_y = get_subsquare_index(sub_pos[0], sub_pos[1])
        subsquare = tile.subgrid[local_x][local_y]

        structure.tick(state, tile, subsquare, tile_pos[0], tile_pos[1])
