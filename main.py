# main.py
"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from config import (
    MAX_POUR_AMOUNT,
    MIN_LAYER_THICKNESS,
    DEPOT_WATER_AMOUNT,
    DEPOT_SCRAP_AMOUNT,
    DEPOT_SEEDS_AMOUNT,
)
from ground import (
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from mapgen import (
    Tile,
    TILE_TYPES,
    generate_map,
    recalculate_biomes,
    update_moisture_history,
)
from player import PlayerState
from structures import (
    Structure,
    build_structure,
    tick_structures,
)
from simulation.surface import simulate_surface_flow, get_tile_surface_water
from simulation.subsurface import simulate_subsurface_tick, apply_tile_evaporation
from weather import WeatherSystem

Point = Tuple[int, int]


@dataclass
class Inventory:
    """Holds player resources in integer units."""
    water: int = 200  # Start with 20.0L (200 units)
    scrap: int = 6
    seeds: int = 2
    biomass: int = 0


@dataclass
class GameState:
    """Main game state container."""
    width: int
    height: int
    tiles: List[List[Tile]]
    structures: Dict[Point, Structure] = field(default_factory=dict)
    player_state: PlayerState = field(default_factory=PlayerState)
    inventory: Inventory = field(default_factory=Inventory)
    weather: WeatherSystem = field(default_factory=WeatherSystem)
    messages: List[str] = field(default_factory=list)

    # === Player convenience properties for backwards compatibility ===
    @property
    def player(self) -> Point:
        """Player tile position (backwards compatibility).

        Returns tile coordinates, not sub-grid coordinates.
        Use player_state.position for sub-grid coordinates.
        """
        return self.player_state.tile_position

    @property
    def player_subsquare(self) -> Point:
        """Player position in sub-grid coordinates."""
        return self.player_state.position

    @property
    def last_rock_blocked(self) -> Point | None:
        return self.player_state.last_rock_blocked

    @last_rock_blocked.setter
    def last_rock_blocked(self, value: Point | None) -> None:
        self.player_state.last_rock_blocked = value

    # === Weather convenience properties ===
    @property
    def day(self) -> int:
        return self.weather.day

    @property
    def turn_in_day(self) -> int:
        return self.weather.turn_in_day

    @property
    def heat(self) -> int:
        return self.weather.heat

    @property
    def rain_timer(self) -> int:
        return self.weather.rain_timer

    @property
    def raining(self) -> bool:
        return self.weather.raining

    @property
    def is_night(self) -> bool:
        return self.weather.is_night

    # === Action Timer Methods (delegate to PlayerState) ===
    def start_action(self, action: str) -> bool:
        """Start an action if not busy. Returns True if action started."""
        return self.player_state.start_action(action)

    def update_action_timer(self, dt: float) -> None:
        """Update action timer by delta time."""
        self.player_state.update_action_timer(dt)

    def is_busy(self) -> bool:
        """Check if player is currently performing an action."""
        return self.player_state.is_busy()

    def get_action_progress(self) -> float:
        """Get progress of current action (0.0 to 1.0)."""
        return self.player_state.get_action_progress()


def build_initial_state(width: int = 10, height: int = 10) -> GameState:
    """Create a new game state with generated map."""
    from subgrid import tile_center_subsquare

    tiles = generate_map(width, height)
    start_tile = (width // 2, height // 2)

    # Set up depot at player start location
    depot_tile = tiles[start_tile[0]][start_tile[1]]
    depot_tile.kind = "flat"
    depot_tile.surface.has_trench = False
    depot_tile.terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    depot_tile.wellspring_output = 0
    depot_tile.depot = True

    # Initialize player at center of starting tile (in sub-grid coords)
    start_subsquare = tile_center_subsquare(start_tile[0], start_tile[1])

    return GameState(
        width=width,
        height=height,
        tiles=tiles,
        player_state=PlayerState(position=start_subsquare),
    )


def dig_trench(state: GameState) -> None:
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.surface.has_trench:
        state.messages.append("Already trenched.")
        return
    tile.surface.has_trench = True
    tile.water.surface_water = max(tile.water.surface_water - 10, 0)
    state.messages.append("Dug a trench; flow improves, evap drops here.")


def terrain_action(state: GameState, action: str) -> None:
    """Dispatch terrain tool actions (shovel submenu)."""
    if action == "trench":
        dig_trench(state)
    elif action == "lower":
        lower_ground(state)
    elif action == "raise":
        raise_ground(state)
    else:
        state.messages.append(f"Unknown terrain action: {action}")


def lower_ground(state: GameState) -> None:
    tile = state.tiles[state.player[0]][state.player[1]]
    for layer, name in [(SoilLayer.TOPSOIL, "topsoil"), (SoilLayer.ELUVIATION, "eluviation"),
                        (SoilLayer.SUBSOIL, "subsoil")]:
        if tile.terrain.get_layer_depth(layer) > MIN_LAYER_THICKNESS:
            removed = tile.terrain.remove_material_from_layer(layer, 2)
            state.messages.append(f"Removed {units_to_meters(removed):.2f}m {name}. Elev: {tile.elevation:.2f}m")
            return
    state.messages.append("Can't dig further - regolith/bedrock too close!")


def raise_ground(state: GameState) -> None:
    if state.inventory.scrap < 1:
        state.messages.append("Need 1 scrap to raise ground.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    state.inventory.scrap -= 1
    tile.terrain.add_material_to_layer(SoilLayer.TOPSOIL, 2)
    state.messages.append(f"Added topsoil (cost 1 scrap). Elev: {tile.elevation:.2f}m")


def collect_water(state: GameState) -> None:
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.depot:
        state.inventory.water += DEPOT_WATER_AMOUNT
        state.inventory.scrap += DEPOT_SCRAP_AMOUNT
        state.inventory.seeds += DEPOT_SEEDS_AMOUNT
        state.messages.append(
            f"Depot resupply: +{DEPOT_WATER_AMOUNT / 10:.1f}L water, +{DEPOT_SCRAP_AMOUNT} scrap, +{DEPOT_SEEDS_AMOUNT} seeds.")
        return

    # Get total surface water from sub-squares in this tile
    available = get_tile_surface_water(tile)
    if available <= 5:
        state.messages.append("No water to collect here.")
        return

    gathered = min(100, available)

    # Remove water proportionally from sub-squares
    remaining = gathered
    total_water = available
    for row in tile.subgrid:
        for subsquare in row:
            if subsquare.surface_water > 0 and remaining > 0:
                proportion = subsquare.surface_water / total_water
                take = min(int(gathered * proportion) + 1, subsquare.surface_water, remaining)
                subsquare.surface_water -= take
                remaining -= take

    state.inventory.water += gathered
    state.messages.append(f"Collected {gathered / 10:.1f}L water.")


def pour_water(state: GameState, amount: float) -> None:
    from simulation.surface import distribute_upward_seepage

    amount_units = int(amount * 10)
    if not (0 < amount_units <= MAX_POUR_AMOUNT):
        state.messages.append(f"Pour between 0.1L and {MAX_POUR_AMOUNT / 10}L.")
        return
    if state.inventory.water < amount_units:
        state.messages.append("Not enough water carried.")
        return

    tile = state.tiles[state.player[0]][state.player[1]]

    # Distribute water to sub-squares (lower elevation gets more)
    distribute_upward_seepage(tile, amount_units)

    state.inventory.water -= amount_units
    state.messages.append(f"Poured {amount:.1f}L water into soil.")


def simulate_tick(state: GameState) -> None:
    """Run one simulation tick.

    Water simulation is split into two phases:
    - Surface flow: Sub-grid level, runs every tick
    - Subsurface flow: Tile level, runs every tick (could be reduced later)
    """
    # Update weather system (day/night cycle, heat, rain)
    weather_messages = state.weather.tick()
    state.messages.extend(weather_messages)

    # Update structures (cisterns, planters, etc.)
    tick_structures(state, state.heat)

    # Track moisture history for biome calculations
    for x in range(state.width):
        for y in range(state.height):
            update_moisture_history(state.tiles[x][y])

    # --- Water Simulation ---
    # Phase 1: Surface flow at sub-grid resolution
    simulate_surface_flow(state.tiles, state.width, state.height)

    # Phase 2: Subsurface flow at tile resolution
    # (includes wellspring output, vertical seepage, horizontal subsurface flow)
    simulate_subsurface_tick(state)

    # Phase 3: Evaporation (applied to sub-squares)
    apply_tile_evaporation(state)


def end_day(state: GameState) -> None:
    messages = state.weather.end_day()
    state.messages.extend(messages)
    # Only recalculate biomes if day actually changed
    if messages and "begins" in messages[-1]:
        biome_messages = recalculate_biomes(state.tiles, state.width, state.height)
        state.messages.extend(biome_messages)


def show_status(state: GameState) -> None:
    inv = state.inventory
    cisterns = [s for s in state.structures.values() if s.kind == "cistern"]
    stored = sum(s.stored for s in cisterns)
    state.messages.append(
        f"Inv: water {inv.water / 10:.1f}L, scrap {inv.scrap}, seeds {inv.seeds}, biomass {inv.biomass}")
    state.messages.append(f"Cisterns: {stored / 10:.1f}L stored across {len(cisterns)} cistern(s)")


def survey_tile(state: GameState) -> None:
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))

    # Get total surface water from sub-squares
    surface_water = get_tile_surface_water(tile)

    desc = [f"Tile {x},{y}", f"type={tile.kind}", f"elev={tile.elevation:.2f}m",
            f"surf={surface_water / 10:.1f}L"]
    if tile.water.total_subsurface_water() > 0:
        desc.append(f"subsrf={tile.water.total_subsurface_water() / 10:.1f}L")
    desc.append(f"topsoil={units_to_meters(tile.terrain.topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(tile.terrain.organics_depth):.1f}m")
    if tile.wellspring_output > 0:
        desc.append(f"wellspring={tile.wellspring_output / 10:.2f}L/t")
    if tile.surface.has_trench:
        desc.append("trench")
    if structure:
        desc.append(f"struct={structure.kind}")
        if structure.kind == "cistern":
            desc.append(f"stored={structure.stored / 10:.1f}L")
        elif structure.kind == "planter":
            desc.append(f"growth={structure.growth}%")
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """Process a player command. Returns True if the game should quit."""
    command_map = {
        "dig": lambda s, a: dig_trench(s),
        "lower": lambda s, a: lower_ground(s),
        "raise": lambda s, a: raise_ground(s),
        "terrain": lambda s, a: terrain_action(s, a[0] if a else ""),
        "build": lambda s, a: build_structure(s, a[0] if a else ""),
        "collect": lambda s, a: collect_water(s),
        "pour": lambda s, a: pour_water(s, float(a[0])) if a else state.messages.append("Usage: pour <liters>"),
        "status": lambda s, a: show_status(s),
        "survey": lambda s, a: survey_tile(s),
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
