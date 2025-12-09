# structures.py
"""
structures.py - Player-built structures for Kemet

Defines structure types, costs, and behavior:
- Cistern: Stores water, reduces evaporation
- Condenser: Generates water from air
- Planter: Grows biomass when watered
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
    STRUCTURE_COSTS,
)

if TYPE_CHECKING:
    from main import GameState


@dataclass
class Structure:
    """Represents a player-built structure on a tile."""
    kind: str
    hp: int = 3
    stored: int = 0  # Water storage in units (cistern)
    growth: int = 0  # Growth progress 0-100 (planter)


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
    if state.inventory.scrap < cost.get("scrap", 0):
        state.messages.append(f"Need {cost.get('scrap', 0)} scrap to build {kind}.")
        return
    if state.inventory.seeds < cost.get("seeds", 0):
        state.messages.append(f"Need {cost.get('seeds', 0)} seeds to build {kind}.")
        return

    state.inventory.scrap -= cost.get("scrap", 0)
    state.inventory.seeds -= cost.get("seeds", 0)

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
                state.inventory.biomass += 1
                state.inventory.seeds += 1
                tile.water.surface_water = max(
                    tile.water.surface_water - PLANTER_WATER_COST, 0
                )

                # Add organics layer on harvest, with a cap
                if tile.terrain.get_layer_depth(SoilLayer.ORGANICS) < MAX_ORGANICS_DEPTH:
                    tile.terrain.add_material_to_layer(SoilLayer.ORGANICS, 1)

                state.messages.append(
                    f"Biomass harvested at {pos}! (Total {state.inventory.biomass})"
                )
