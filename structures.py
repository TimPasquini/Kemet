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
    STRUCTURE_COSTS,
)
from simulation.surface import get_tile_surface_water, distribute_upward_seepage

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
    if tile.depot:
        state.messages.append("Cannot build on depot.")
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

    state.structures[sub_pos] = Structure(kind=kind)
    subsquare.structure_id = len(state.structures)  # Mark sub-square as having structure
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

        if structure.kind == "condenser":
            # Add water to sub-squares (distributed by elevation)
            distribute_upward_seepage(tile, CONDENSER_OUTPUT)

        elif structure.kind == "cistern":
            # Get total surface water from sub-squares
            surface_water = get_tile_surface_water(tile)

            # Transfer surface water into cistern storage
            if surface_water > CISTERN_TRANSFER_RATE and structure.stored < CISTERN_CAPACITY:
                transfer = min(
                    CISTERN_TRANSFER_RATE,
                    surface_water,
                    CISTERN_CAPACITY - structure.stored
                )
                # Remove water proportionally from sub-squares
                _remove_water_from_subgrid(tile, transfer)
                structure.stored += transfer

            # Cistern slowly leaks (scales with heat)
            loss = (CISTERN_LOSS_RATE * heat) // 100
            drained = min(structure.stored, loss)
            structure.stored -= drained
            recovered = (drained * CISTERN_LOSS_RECOVERY) // 100
            distribute_upward_seepage(tile, recovered)

        elif structure.kind == "planter":
            # Total water includes sub-square surface water + subsurface
            surface_water = get_tile_surface_water(tile)
            total_water = surface_water + tile.water.total_subsurface_water()

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

                # Remove water cost from sub-squares
                _remove_water_from_subgrid(tile, PLANTER_WATER_COST)

                # Add organics to this sub-square's terrain (create override if needed)
                terrain = ensure_terrain_override(subsquare, tile.terrain)
                if terrain.get_layer_depth(SoilLayer.ORGANICS) < MAX_ORGANICS_DEPTH:
                    terrain.add_material_to_layer(SoilLayer.ORGANICS, 1)

                state.messages.append(
                    f"Biomass harvested at {sub_pos}! (Total {state.inventory.biomass})"
                )


def _remove_water_from_subgrid(tile, amount: int) -> int:
    """Remove water proportionally from tile's sub-squares.

    Args:
        tile: Tile to remove water from
        amount: Amount to remove

    Returns:
        Actual amount removed
    """
    total_water = get_tile_surface_water(tile)
    if total_water <= 0:
        return 0

    to_remove = min(amount, total_water)
    remaining = to_remove

    for row in tile.subgrid:
        for subsquare in row:
            if subsquare.surface_water > 0 and remaining > 0:
                proportion = subsquare.surface_water / total_water
                take = min(int(to_remove * proportion) + 1, subsquare.surface_water, remaining)
                subsquare.surface_water -= take
                remaining -= take

    return to_remove - remaining
