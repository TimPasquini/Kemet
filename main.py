# main.py
"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ground import (
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from water import (
    simulate_vertical_seepage,
    calculate_surface_flow,
    calculate_subsurface_flow,
    calculate_overflows,
    apply_flows,
)
from structures import (
    Structure,
    build_structure,
    tick_structures,
)
from weather import WeatherSystem
from mapgen import (
    Tile,
    TileType,
    TILE_TYPES,
    generate_map,
    recalculate_biomes,
    update_moisture_history,
)
from config import (
    HEAT_NIGHT_THRESHOLD,
    MAX_POUR_AMOUNT,
    MIN_LAYER_THICKNESS,
    DEPOT_WATER_AMOUNT,
    DEPOT_SCRAP_AMOUNT,
    DEPOT_SEEDS_AMOUNT,
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
    RAIN_WELLSPRING_MULTIPLIER,
)
from player import PlayerState

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
        """Player position (backwards compatibility)."""
        return self.player_state.position

    @player.setter
    def player(self, value: Point) -> None:
        self.player_state.position = value

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
    tiles = generate_map(width, height)
    start_pos = (width // 2, height // 2)

    # Set up depot at player start location
    depot_tile = tiles[start_pos[0]][start_pos[1]]
    depot_tile.kind = "flat"
    depot_tile.surface.has_trench = False
    depot_tile.terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    depot_tile.wellspring_output = 0
    depot_tile.depot = True

    return GameState(
        width=width,
        height=height,
        tiles=tiles,
        player_state=PlayerState(position=start_pos),
    )


def render(state: GameState) -> None:
    print("\n" * 2)
    phase = "Night" if state.heat < HEAT_NIGHT_THRESHOLD else "Day"
    print(
        f"Day {state.day} [{phase}] Heat {state.heat}%  Rain in {state.rain_timer} ({'on' if state.raining else 'off'})")
    inv = state.inventory
    print(f"Water {inv.water / 10:.1f}L | Scrap {inv.scrap} | Seeds {inv.seeds} | Biomass {inv.biomass}")
    print("Legend: @ you, D depot, C cistern, N condenser, P planter, = trench, ~ wet, : damp")
    print("Map:")
    for y in range(state.height):
        row = []
        for x in range(state.width):
            pos = (x, y)
            tile = state.tiles[x][y]
            structure = state.structures.get(pos)
            symbol = TILE_TYPES[tile.kind].char
            if tile.water.total_water() >= 100:
                symbol = "~"
            elif tile.water.total_water() >= 50:
                symbol = ":"
            if tile.surface.has_trench: symbol = "="
            if tile.depot: symbol = "D"
            if structure: symbol = {"cistern": "C", "condenser": "N", "planter": "P"}.get(structure.kind, "?")
            if state.player == pos: symbol = "@"
            row.append(symbol)
        print("".join(row))
    if state.messages:
        print("Events:")
        for msg in state.messages[-5:]:
            print(f"- {msg}")


def parse_command(raw: str) -> Tuple[str, List[str]]:
    parts = raw.strip().lower().split()
    return (parts[0], parts[1:]) if parts else ("", [])


def move_player(state: GameState, direction: str) -> None:
    dxdy = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
    if direction not in dxdy:
        state.messages.append("Unknown move.")
        return
    dx, dy = dxdy[direction]
    nx, ny = state.player[0] + dx, state.player[1] + dy
    if 0 <= nx < state.width and 0 <= ny < state.height:
        if state.tiles[nx][ny].kind == "rock":
            state.messages.append("Rock blocks the way.")
            return
        state.player = (nx, ny)
        state.messages.append(f"Moved to {nx},{ny}.")
    else:
        state.messages.append("You hit the edge of the desert.")


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
    available = tile.water.surface_water
    if available <= 5:
        state.messages.append("No water to collect here.")
        return
    gathered = min(100, available)
    tile.water.surface_water -= gathered
    state.inventory.water += gathered
    state.messages.append(f"Collected {gathered / 10:.1f}L water.")


def pour_water(state: GameState, amount: float) -> None:
    amount_units = int(amount * 10)
    if not (0 < amount_units <= MAX_POUR_AMOUNT):
        state.messages.append(f"Pour between 0.1L and {MAX_POUR_AMOUNT / 10}L.")
        return
    if state.inventory.water < amount_units:
        state.messages.append("Not enough water carried.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    tile.water.surface_water += amount_units
    state.inventory.water -= amount_units
    state.messages.append(f"Poured {amount:.1f}L water into soil.")


def simulate_tick(state: GameState) -> None:
    # Update weather system (day/night cycle, heat, rain)
    weather_messages = state.weather.tick()
    state.messages.extend(weather_messages)

    tick_structures(state, state.heat)

    # --- Water Simulation Steps ---
    # 1. Add water from sources and move it vertically
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            update_moisture_history(tile)
            if tile.wellspring_output > 0:
                gain = tile.wellspring_output * (RAIN_WELLSPRING_MULTIPLIER if state.raining else 100) // 100
                tile.water.add_layer_water(SoilLayer.REGOLITH, gain)
            simulate_vertical_seepage(tile.terrain, tile.water)

    # Create a snapshot of the tile data for flow calculations
    tiles_data = [[(state.tiles[x][y].terrain, state.tiles[x][y].water) for y in range(state.height)] for x in
                  range(state.width)]

    # 2. Calculate and apply all horizontal flows
    trench_map = {(x, y): state.tiles[x][y].surface.has_trench for x in range(state.width) for y in range(state.height)}
    overflow_sub_deltas, overflow_surf_deltas = calculate_overflows(tiles_data, state.width, state.height)
    surface_deltas = calculate_surface_flow(tiles_data, state.width, state.height, trench_map)
    subsurface_deltas = calculate_subsurface_flow(tiles_data, state.width, state.height)

    # Combine deltas before applying
    for key, value in overflow_sub_deltas.items():
        subsurface_deltas[key] = subsurface_deltas.get(key, 0) + value
    for key, value in overflow_surf_deltas.items():
        surface_deltas[key] = surface_deltas.get(key, 0) + value

    apply_flows(tiles_data, surface_deltas, subsurface_deltas)

    # 3. Apply evaporation after all water has moved
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            evap = (TILE_TYPES[tile.kind].evap * state.heat) // 100
            if tile.surface.has_trench:
                evap = (evap * TRENCH_EVAP_REDUCTION) // 100
            if (x, y) in state.structures and state.structures[(x, y)].kind == "cistern":
                evap = (evap * CISTERN_EVAP_REDUCTION) // 100
            net_loss = evap - ((TILE_TYPES[tile.kind].retention * evap) // 100)
            tile.water.surface_water = max(0, tile.water.surface_water - net_loss)


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
    desc = [f"Tile {x},{y}", f"type={tile.kind}", f"elev={tile.elevation:.2f}m",
            f"surf={tile.water.surface_water / 10:.1f}L"]
    if tile.water.total_subsurface_water() > 0: desc.append(f"subsrf={tile.water.total_subsurface_water() / 10:.1f}L")
    desc.append(f"topsoil={units_to_meters(tile.terrain.topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(tile.terrain.organics_depth):.1f}m")
    if tile.wellspring_output > 0: desc.append(f"wellspring={tile.wellspring_output / 10:.2f}L/t")
    if tile.surface.has_trench: desc.append("trench")
    if structure:
        desc.append(f"struct={structure.kind}")
        if structure.kind == "cistern":
            desc.append(f"stored={structure.stored / 10:.1f}L")
        elif structure.kind == "planter":
            desc.append(f"growth={structure.growth}%")
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """Process a player command using a command map. Returns True if the game should quit."""
    command_map = {
        "w": lambda s, a: move_player(s, "w"),
        "a": lambda s, a: move_player(s, "a"),
        "s": lambda s, a: move_player(s, "s"),
        "d": lambda s, a: move_player(s, "d"),
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
    if cmd == "quit": return True
    if cmd == "help":
        state.messages.append(
            "Commands: w/a/s/d, dig, lower, raise, build <type>, collect, pour <liters>, survey, status, end, quit")
        return False
    handler = command_map.get(cmd)
    if not handler:
        state.messages.append("Unknown command. Type 'help' for options.")
        return False
    try:
        handler(state, args)
    except (TypeError, ValueError, IndexError):
        state.messages.append(f"Invalid usage for '{cmd}'. Check 'help'.")
    return False


def main() -> None:
    random.seed()
    state = build_initial_state()
    state.messages.extend([
        "You arrive with a cart of scrap, a few seeds, and two canteens of water.",
        "Find water, trap it, and grow biomass.",
        "Units: 1L water = 10 units, 1m soil = 10 units"
    ])
    while True:
        render(state)
        raw = input("\nCommand> ")
        cmd, args = parse_command(raw)
        if not cmd:
            continue
        if handle_command(state, cmd, args):
            print("Exiting. Thanks for playing the prototype.")
            break
        if cmd not in ("status", "help", "survey"):
            simulate_tick(state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
