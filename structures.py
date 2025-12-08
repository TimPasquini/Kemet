"""
structures.py - Player-built structures for Kemet

Defines structure types, costs, and behavior:
- Cistern: Stores water, reduces evaporation
- Condenser: Generates water from air
- Planter: Grows biomass when watered
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Union, TYPE_CHECKING

from ground import SoilLayer

if TYPE_CHECKING:
    from main import GameState, Tile

# Structure behavior constants
CONDENSER_OUTPUT = 2  # Units of water per tick (0.2L)
PLANTER_GROWTH_RATE = 25  # Growth points per tick (out of 100)
PLANTER_GROWTH_THRESHOLD = 100
PLANTER_WATER_COST = 3  # Units of water consumed on harvest
PLANTER_WATER_REQUIREMENT = 80  # Units (8L) needed for growth

# Cistern constants
CISTERN_CAPACITY = 500  # Units (50L)
CISTERN_TRANSFER_RATE = 40  # Units per tick
CISTERN_LOSS_RATE = 3  # Units per tick at max heat
CISTERN_LOSS_RECOVERY = 50  # Percentage returned to surface

# Evaporation reduction multipliers (percentage - lower = more reduction)
TRENCH_EVAP_REDUCTION = 85  # 85% = 15% reduction
CISTERN_EVAP_REDUCTION = 40  # 40% = 60% reduction


@dataclass
class Structure:
    """Represents a player-built structure on a tile."""
    kind: str
    hp: int = 3
    stored: int = 0  # Water storage in units (cistern)
    growth: int = 0  # Growth progress 0-100 (planter)


STRUCTURE_COSTS: Dict[str, Dict[str, Union[int, float]]] = {
    "cistern": {"scrap": 3},
    "condenser": {"scrap": 2},
    "planter": {"scrap": 1, "seeds": 1},
}


def build_structure(state: "GameState", kind: str) -> None:
    """Build a structure on current tile."""
    kind = kind.lower()
    if kind not in STRUCTURE_COSTS:
        state.messages.append("Cannot build that.")
        return

    pos = state.player
    if pos in state.structures:
        state.messages.append("Tile already occupied.")
        return

    cost = STRUCTURE_COSTS[kind]
    for resource, needed in cost.items():
        if state.inventory.get(resource, 0) < needed:
            state.messages.append(f"Need more {resource} to build {kind}.")
            return

    for resource, needed in cost.items():
        current = state.inventory[resource]
        if isinstance(needed, int):
            state.inventory[resource] = int(current) - needed
        else:
            state.inventory[resource] = float(current) - needed

    state.structures[pos] = Structure(kind=kind)
    state.tiles[pos[0]][pos[1]].surface.has_structure = True
    state.messages.append(f"Built {kind} at {pos}.")


def tick_structures(state: "GameState", heat: int) -> None:
    """Update all structures for one simulation tick."""
    for pos, structure in list(state.structures.items()):
        tile = state.tiles[pos[0]][pos[1]]

        if structure.kind == "condenser":
            tile.water.surface_water += CONDENSER_OUTPUT

        elif structure.kind == "cistern":
            # Transfer surface water into cistern storage
            if tile.water.surface_water > CISTERN_TRANSFER_RATE and structure.stored < CISTERN_CAPACITY:
                transfer = min(
                    CISTERN_TRANSFER_RATE,
                    tile.water.surface_water,
                    CISTERN_CAPACITY - structure.stored
                )
                tile.water.surface_water -= transfer
                structure.stored += transfer

            # Cistern slowly leaks (scales with heat)
            loss = (CISTERN_LOSS_RATE * heat) // 100
            drained = min(structure.stored, loss)
            structure.stored -= drained
            recovered = (drained * CISTERN_LOSS_RECOVERY) // 100
            tile.water.surface_water += recovered

        elif structure.kind == "planter":
            total_water = tile.water.total_water()
            if total_water >= PLANTER_WATER_REQUIREMENT:
                structure.growth += PLANTER_GROWTH_RATE
                if structure.growth > PLANTER_GROWTH_THRESHOLD:
                    structure.growth = PLANTER_GROWTH_THRESHOLD
            else:
                structure.growth = max(structure.growth - 10, 0)

            if structure.growth >= PLANTER_GROWTH_THRESHOLD:
                structure.growth = 0
                state.inventory["biomass"] = int(state.inventory["biomass"]) + 1
                state.inventory["seeds"] = int(state.inventory["seeds"]) + 1
                tile.water.surface_water = max(
                    tile.water.surface_water - PLANTER_WATER_COST, 0
                )

                # Add organics layer on harvest
                tile.terrain.add_material_to_layer(SoilLayer.ORGANICS, 1)

                state.messages.append(
                    f"Biomass harvested at {pos}! (Total {state.inventory['biomass']})"
                )
