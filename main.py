# main.py
"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import collections
from typing import List, Tuple

import numpy as np
from config import GRID_WIDTH, GRID_HEIGHT
from config import MOISTURE_EMA_ALPHA
from world.terrain import (
    SoilLayer,
    units_to_meters,
)
from world.biomes import recalculate_biomes
from structures import (
    build_structure,
    tick_structures,
)
from simulation.surface import (
    simulate_surface_flow,
    simulate_surface_seepage,
)
from simulation.subsurface import apply_surface_evaporation
from simulation.subsurface_vectorized import simulate_subsurface_tick_vectorized
from simulation.erosion import apply_overnight_erosion, accumulate_wind_exposure
from game_state import GameState
from game_state.terrain_actions import terrain_action
from game_state.player_actions import collect_water, pour_water

Point = Tuple[int, int]


def simulate_tick(state: GameState) -> None:
    """Run one simulation tick using active sets for performance."""
    weather_messages = state.weather.tick()
    state.messages.extend(weather_messages)
    tick_structures(state, state.heat)

    tick = state.weather.turn_in_day

    if tick % 2 == 0:
        simulate_surface_flow(state)

    if tick % 2 == 1:
        # Seepage still iterates all grid cells, but is less frequent.
        # Could be optimized further by tracking active surface water cells.
        simulate_surface_seepage(state)
        
        # Update moisture history using fully vectorized approach
        # Calculate current total water (surface + subsurface) at grid resolution
        subsurface_total = np.sum(state.subsurface_water_grid, axis=0)  # Sum all 6 layers -> (180, 135)
        current_moisture_grid = state.water_grid + subsurface_total  # Both (180, 135)

        if state.moisture_grid is None:
            state.moisture_grid = current_moisture_grid.astype(float)
        else:
            # Apply Exponential Moving Average
            state.moisture_grid = (1 - MOISTURE_EMA_ALPHA) * state.moisture_grid + MOISTURE_EMA_ALPHA * current_moisture_grid

    if tick % 4 == 1:
        simulate_subsurface_tick_vectorized(state)

    apply_surface_evaporation(state)

    # Update atmosphere every 2 ticks for performance (not every tick)
    if tick % 2 == 0:
        # NEW: Grid-based vectorized atmosphere
        if state.humidity_grid is not None and state.wind_grid is not None:
            from simulation.atmosphere import simulate_atmosphere_tick_vectorized
            simulate_atmosphere_tick_vectorized(state)

    # Accumulate wind exposure every 10 ticks
    if tick % 10 == 0:
        accumulate_wind_exposure(state)


def end_day(state: GameState) -> None:
    messages = state.weather.end_day()
    state.messages.extend(messages)
    if messages and "begins" in messages[-1]:
        erosion_messages = apply_overnight_erosion(state)
        state.messages.extend(erosion_messages)

        # Pass moisture grid directly to biome recalculation (operates at grid cell resolution)
        if state.moisture_grid is not None:
            biome_messages = recalculate_biomes(state, state.moisture_grid)
        else:
            # Create empty moisture grid if not initialized
            biome_messages = recalculate_biomes(state, np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float))
        state.messages.extend(biome_messages)


def show_status(state: GameState) -> None:
    inv = state.inventory
    state.messages.append(
        f"Inv: water {inv.water / 10:.1f}L, scrap {inv.scrap}, seeds {inv.seeds}, biomass {inv.biomass}")

    summaries = collections.defaultdict(int)
    structure_counts = collections.defaultdict(int)
    for s in state.structures.values():
        summary = s.get_status_summary()
        if summary:
            structure_counts[s.kind] += 1
            for key, value in summary.items():
                summaries[key] += value

    if "stored_water" in summaries:
        num_cisterns = structure_counts.get("cistern", 0)
        state.messages.append(f"Cisterns: {summaries['stored_water'] / 10:.1f}L stored across {num_cisterns} cistern(s)")

def survey_cell(state: GameState) -> None:
    """Survey tool - display grid cell information (array-based)."""
    grid_pos = state.get_action_target_cell()
    x, y = grid_pos
    structure = state.structures.get(grid_pos)
    surface_water = state.water_grid[x, y]

    # Calculate elevation from grids
    from grid_helpers import get_total_elevation
    elev_m = get_total_elevation(state, x, y)

    desc = [f"Cell ({x},{y})", f"elev={elev_m:.2f}m",
            f"surf={surface_water / 10:.1f}L"]

    # Get subsurface water from grid
    subsurface_total = int(np.sum(state.subsurface_water_grid[:, x, y]))
    if subsurface_total > 0:
        desc.append(f"subsrf={subsurface_total / 10:.1f}L")

    # Get exposed material (what the player sees on the surface)
    from grid_helpers import get_exposed_material
    material = get_exposed_material(state, x, y)
    desc.append(f"material={material}")

    # Get layer depths from terrain_layers grid
    topsoil_depth = state.terrain_layers[SoilLayer.TOPSOIL, x, y]
    organics_depth = state.terrain_layers[SoilLayer.ORGANICS, x, y]
    desc.append(f"topsoil={units_to_meters(topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(organics_depth):.1f}m")

    # Get wellspring from wellspring_grid
    wellspring_output = state.wellspring_grid[x, y]
    if wellspring_output > 0:
        desc.append(f"wellspring={wellspring_output / 10:.2f}L/t")

    if state.trench_grid[x, y]:
        desc.append("trench")
    if structure:
        desc.append(structure.get_survey_string())
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """Process a player command. Returns True if the game should quit."""
    command_map = {
        "terrain": lambda s, a: terrain_action(s, a[0] if a else "", a[1:]),
        "build": lambda s, a: build_structure(s, a[0]) if a else s.messages.append("Usage: build <type>"),
        "collect": lambda s, a: collect_water(s),
        "pour": lambda s, a: pour_water(s, float(a[0])) if a else s.messages.append("Usage: pour <liters>"),
        "status": lambda s, a: show_status(s),
        "survey": lambda s, a: survey_cell(s),
        "end": lambda s, a: end_day(s),
    }
    if cmd == "quit":
        return True
    handler = command_map.get(cmd)
    if not handler:
        state.messages.append(f"Unknown command: {cmd}")
        return False
    try:
        handler(state, args)
    except (TypeError, ValueError, IndexError):
        state.messages.append(f"Invalid usage for '{cmd}'.")
    return False
