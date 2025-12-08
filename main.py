# main.py
"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ground import (
    TerrainColumn,
    SurfaceTraits,
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from water import (
    WaterColumn,
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
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)
# Import from our new utils file
from utils import get_neighbors

Point = Tuple[int, int]

# Day/night cycle constants
DAY_LENGTH = 1200  # 1200 ticks at 0.25s/tick = 300s = 5 minute day
HEAT_MIN = 60
HEAT_MAX = 140
HEAT_NIGHT_THRESHOLD = 90

# Input validation limits
MAX_POUR_AMOUNT = 1000  # 100L
MIN_LAYER_THICKNESS = 1

# Depot resupply amounts
DEPOT_WATER_AMOUNT = 300  # 30L
DEPOT_SCRAP_AMOUNT = 3
DEPOT_SEEDS_AMOUNT = 1


@dataclass
class TileType:
    name: str
    char: str
    evap: int
    capacity: int
    retention: int


TILE_TYPES: Dict[str, TileType] = {
    "dune": TileType("dune", ".", evap=12, capacity=60, retention=5),
    "flat": TileType("flat", ",", evap=9, capacity=90, retention=8),
    "wadi": TileType("wadi", "w", evap=5, capacity=140, retention=20),
    "rock": TileType("rock", "^", evap=6, capacity=50, retention=2),
    "salt": TileType("salt", "_", evap=14, capacity=70, retention=3),
}

MOISTURE_HISTORY_MAX = 24


@dataclass
class Tile:
    kind: str
    terrain: TerrainColumn
    water: WaterColumn
    surface: SurfaceTraits
    wellspring_output: int = 0
    depot: bool = False
    moisture_history: List[int] = field(default_factory=list)

    @property
    def elevation(self) -> float:
        return units_to_meters(self.terrain.get_surface_elevation())

    @property
    def hydration(self) -> float:
        return self.water.total_water() / 10.0

    @property
    def trench(self) -> bool:
        return self.surface.has_trench

    @trench.setter
    def trench(self, value: bool) -> None:
        self.surface.has_trench = value


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
    player: Point = (0, 0)
    inventory: Inventory = field(default_factory=Inventory)
    day: int = 1
    turn_in_day: int = 0
    heat: int = 100
    rain_timer: int = 1200
    raining: bool = False
    is_night: bool = False
    messages: List[str] = field(default_factory=list)
    # Pygame frontend state (action timer system)
    player_action_timer: float = 0.0
    last_action: str = ""
    # Track last rock tile that blocked movement (to avoid message spam)
    last_rock_blocked: Point | None = None


def update_moisture_history(tile: Tile) -> None:
    tile.moisture_history.append(tile.water.total_water())
    if len(tile.moisture_history) > MOISTURE_HISTORY_MAX:
        tile.moisture_history.pop(0)


def get_average_moisture(tile: Tile) -> float:
    if not tile.moisture_history:
        return float(tile.water.total_water())
    return sum(tile.moisture_history) / len(tile.moisture_history)


def calculate_biome(tile: Tile, neighbor_tiles: List[Tile], elevation_percentile: float) -> str:
    avg_moisture = get_average_moisture(tile)
    soil_depth = tile.terrain.get_total_soil_depth()
    topsoil_material = tile.terrain.topsoil_material

    if elevation_percentile > 0.75 and soil_depth < 5:
        return "rock"
    if elevation_percentile < 0.25 and avg_moisture > 50:
        return "wadi"
    if topsoil_material == "sand" and avg_moisture < 20:
        return "dune"
    if elevation_percentile < 0.4 and avg_moisture < 15 and tile.terrain.organics_depth == 0:
        return "salt"

    if neighbor_tiles:
        neighbor_biomes = [n.kind for n in neighbor_tiles]
        biome_counts = Counter(neighbor_biomes)
        most_common_list = biome_counts.most_common(1)
        if most_common_list:
            most_common, count = most_common_list[0]
            if count >= 3 and most_common in ("dune", "flat", "wadi"):
                return most_common
    return "flat"


def calculate_elevation_percentiles(state: "GameState") -> Dict[Point, float]:
    elevation_data = []
    for x in range(state.width):
        for y in range(state.height):
            elevation_data.append((state.tiles[x][y].elevation, (x, y)))
    elevation_data.sort(key=lambda e: e[0])
    percentiles = {}
    total = len(elevation_data)
    for i, (elev, pos) in enumerate(elevation_data):
        percentiles[pos] = i / max(1, total - 1)
    return percentiles


def recalculate_biomes(state: "GameState") -> None:
    percentiles = calculate_elevation_percentiles(state)
    changes = 0
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            if tile.depot:
                continue
            neighbor_tiles = [state.tiles[nx][ny] for nx, ny in get_neighbors(x, y, state.width, state.height)]
            elev_pct = percentiles.get((x, y), 0.5)
            new_biome = calculate_biome(tile, neighbor_tiles, elev_pct)
            if new_biome != tile.kind:
                tile.kind = new_biome
                changes += 1
    if changes > 0:
        state.messages.append(f"Landscape shifted: {changes} tiles changed biome.")


def wfc_like_map(width: int, height: int) -> List[List[Tile]]:
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }
    bedrock_base = elevation_to_units(random.uniform(-2.5, -2.0))
    tiles: List[List[Tile]] = [
        [Tile("flat", create_default_terrain(bedrock_base, elevation_to_units(1.0)), WaterColumn(), SurfaceTraits()) for
         _ in range(height)]
        for _ in range(width)
    ]
    positions = [(x, y) for x in range(width) for y in range(height)]
    random.shuffle(positions)
    for x, y in positions:
        neighbor_types = [tiles[nx][ny].kind for nx, ny in get_neighbors(x, y, width, height)]
        weighted: Dict[str, int] = {}
        for kind, base_w in base_weights.items():
            weight = base_w
            for n in neighbor_types:
                weight += adjacency.get(n, {}).get(kind, 0)
            weighted[kind] = weight
        choice = random.choices(list(weighted.keys()), weights=weighted.values(), k=1)[0]
        depth_map = {"dune": random.uniform(1.5, 2.5), "flat": random.uniform(1.0, 2.0),
                     "wadi": random.uniform(0.5, 1.2), "rock": random.uniform(0.2, 0.6),
                     "salt": random.uniform(0.8, 1.5)}
        bedrock_elev = bedrock_base + elevation_to_units(random.uniform(-0.3, 0.3))
        total_soil = elevation_to_units(depth_map[choice])
        tiles[x][y] = Tile(choice, create_default_terrain(bedrock_elev, total_soil), WaterColumn(), SurfaceTraits())

        # Saturate the regolith layer to create a base water table
        regolith_capacity = tiles[x][y].terrain.get_max_water_storage(SoilLayer.REGOLITH)
        tiles[x][y].water.set_layer_water(SoilLayer.REGOLITH, regolith_capacity)

    _generate_wellsprings(tiles, width, height)
    for x in range(width):
        for y in range(height):
            if tiles[x][y].kind == "wadi":
                tiles[x][y].water.surface_water += random.randint(5, 30)
    return tiles


def _generate_wellsprings(tiles: List[List[Tile]], width: int, height: int) -> None:
    all_tiles = [(x, y, tiles[x][y].elevation) for x in range(width) for y in range(height)]
    all_tiles.sort(key=lambda t: t[2])
    lowland_count = max(1, len(all_tiles) // 4)
    lowland_candidates = all_tiles[:lowland_count]
    px, py, _ = random.choice(lowland_candidates)
    tiles[px][py].kind = "wadi"
    tiles[px][py].wellspring_output = random.randint(8, 12)
    # Wellsprings start extra saturated
    tiles[px][py].water.add_layer_water(SoilLayer.REGOLITH, 100)
    tiles[px][py].water.surface_water = 80
    secondary_count = random.randint(1, 2)
    attempts, placed = 0, 0
    while placed < secondary_count and attempts < 20:
        sx, sy = random.randrange(width), random.randrange(height)
        attempts += 1
        if tiles[sx][sy].wellspring_output > 0 or (sx, sy) == (width // 2, height // 2):
            continue
        tiles[sx][sy].wellspring_output = random.randint(2, 6)
        tiles[sx][sy].water.add_layer_water(SoilLayer.REGOLITH, 30)
        tiles[sx][sy].water.surface_water = 20
        placed += 1


def build_initial_state(width: int = 10, height: int = 10) -> GameState:
    tiles = wfc_like_map(width, height)
    player = (width // 2, height // 2)
    depot_tile = tiles[player[0]][player[1]]
    depot_tile.kind = "flat"
    depot_tile.surface.has_trench = False
    depot_tile.terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    depot_tile.wellspring_output = 0
    depot_tile.depot = True
    return GameState(width=width, height=height, tiles=tiles, player=player)


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
    if not state.is_night:
        state.turn_in_day += 1
        # Correctly calculate heat based on progress through the current day
        day_factor = (1 - abs((state.turn_in_day / (DAY_LENGTH - 1)) * 2 - 1)) if DAY_LENGTH > 1 else 1.0
        state.heat = HEAT_MIN + int((HEAT_MAX - HEAT_MIN) * day_factor)
        if state.turn_in_day >= DAY_LENGTH:
            state.is_night = True
            state.heat = HEAT_MIN
            state.messages.append("Night falls. Press Space to rest.")

    state.rain_timer -= 1
    if state.raining:
        if state.rain_timer <= 0:
            state.raining = False
            # Scale up time between rain
            state.rain_timer = random.randint(1200, 2000)
            state.messages.append("Rain fades.")
    elif state.rain_timer <= 0:
        state.raining = True
        # Scale up rain duration
        state.rain_timer = random.randint(300, 500)
        state.messages.append("Rain arrives! Wellsprings surge.")

    tick_structures(state, state.heat)

    # --- Water Simulation Steps ---
    # 1. Add water from sources and move it vertically
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            update_moisture_history(tile)
            if tile.wellspring_output > 0:
                gain = tile.wellspring_output * (150 if state.raining else 100) // 100
                tile.water.add_layer_water(SoilLayer.REGOLITH, gain)
            simulate_vertical_seepage(tile.terrain, tile.water)

    # Create a snapshot of the tile data for flow calculations
    tiles_data = [[(state.tiles[x][y].terrain, state.tiles[x][y].water) for y in range(state.height)] for x in
                  range(state.width)]

    # 2. Calculate and apply all horizontal flows
    trench_map = {(x, y): state.tiles[x][y].surface.has_trench for x in range(state.width) for y in range(state.height)}
    overflow_deltas = calculate_overflows(tiles_data, state.width, state.height)
    surface_deltas = calculate_surface_flow(tiles_data, state.width, state.height, trench_map)
    subsurface_deltas = calculate_subsurface_flow(tiles_data, state.width, state.height)

    # Combine deltas before applying
    for key, value in overflow_deltas.items():
        subsurface_deltas[key] = subsurface_deltas.get(key, 0) + value

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
    if not state.is_night:
        state.messages.append("Can only rest at night. Wait for day to end.")
        return
    state.day += 1
    state.turn_in_day = 0
    state.is_night = False
    state.heat = 100
    state.messages.append(f"Day {state.day} begins.")
    recalculate_biomes(state)


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
    """Process a player command using a command map. Returns True if should quit."""
    command_map = {
        "w": move_player, "a": move_player, "s": move_player, "d": move_player,
        "dig": dig_trench, "lower": lower_ground, "raise": raise_ground,
        "terrain": terrain_action,  # Shovel tool dispatcher
        "build": build_structure, "collect": collect_water, "pour": pour_water,
        "status": show_status, "survey": survey_tile, "end": end_day,
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
        if cmd in ("w", "a", "s", "d"):
            handler(state, cmd)
        elif cmd == "pour":
            handler(state, float(args[0]))
        else:
            handler(state, *args)
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
