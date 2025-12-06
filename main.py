"""
Kemet – Desert Farm Prototype
Turn-based ASCII simulation: explore, capture water, build, and green a patch.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

Point = Tuple[int, int]


@dataclass
class TileType:
    name: str
    char: str
    evap: float
    capacity: float
    retention: float


TILE_TYPES: Dict[str, TileType] = {
    "dune": TileType("dune", ".", evap=0.12, capacity=0.6, retention=0.05),
    "flat": TileType("flat", ",", evap=0.09, capacity=0.9, retention=0.08),
    "wadi": TileType("wadi", "w", evap=0.05, capacity=1.4, retention=0.2),
    "rock": TileType("rock", "^", evap=0.06, capacity=0.5, retention=0.02),
    "salt": TileType("salt", "_", evap=0.14, capacity=0.7, retention=0.03),
}


@dataclass
class Tile:
    kind: str
    hydration: float = 0.0
    trench: bool = False
    elevation: float = 0.0
    well_output: float = 0.0
    depot: bool = False


@dataclass
class Structure:
    kind: str
    hp: int = 3
    stored: float = 0.0
    growth: float = 0.0


STRUCTURE_COSTS = {
    "cistern": {"scrap": 3},
    "condenser": {"scrap": 2},
    "planter": {"scrap": 1, "seeds": 1},
}


@dataclass
class GameState:
    width: int
    height: int
    tiles: List[List[Tile]]
    structures: Dict[Point, Structure] = field(default_factory=dict)
    player: Point = (0, 0)
    inventory: Dict[str, float] = field(
        default_factory=lambda: {"water": 2.0, "scrap": 6, "seeds": 2, "biomass": 0}
    )
    day: int = 1
    turn_in_day: int = 0
    heat: float = 1.0
    dust_timer: int = 8
    rain_timer: int = 12
    raining: bool = False
    messages: List[str] = field(default_factory=list)


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def neighbors(x: int, y: int, width: int, height: int) -> List[Point]:
    options = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            options.append((nx, ny))
    return options


def wfc_like_map(width: int, height: int) -> List[List[Tile]]:
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    tiles: List[List[Tile]] = [[None for _ in range(height)] for _ in range(width)]  # type: ignore
    positions = [(x, y) for x in range(width) for y in range(height)]
    random.shuffle(positions)

    for x, y in positions:
        neighbor_types = [tiles[nx][ny].kind for nx, ny in neighbors(x, y, width, height) if tiles[nx][ny]]
        weighted: Dict[str, int] = {}
        for kind, base_w in base_weights.items():
            weight = base_w
            for n in neighbor_types:
                weight += adjacency.get(n, {}).get(kind, 0)
            weighted[kind] = weight
        choice = random.choices(list(weighted.keys()), weights=weighted.values(), k=1)[0]
        elevation = {
            "dune": random.uniform(1.2, 2.0),
            "flat": random.uniform(0.8, 1.4),
            "wadi": random.uniform(0.2, 0.8),
            "rock": random.uniform(1.0, 1.8),
            "salt": random.uniform(0.6, 1.0),
        }[choice]
        tiles[x][y] = Tile(choice, elevation=elevation)

    # Seed wells (fixed sources) and wet wadis.
    wells = random.randint(3, 4)
    for _ in range(wells):
        rx, ry = random.randrange(width), random.randrange(height)
        tiles[rx][ry].kind = "wadi"
        # Varying rates: seep vs spring
        tiles[rx][ry].well_output = random.choice(
            [random.uniform(0.12, 0.25), random.uniform(0.35, 0.6)]
        )
        tiles[rx][ry].hydration += 0.4
    for x in range(width):
        for y in range(height):
            if tiles[x][y].kind == "wadi":
                tiles[x][y].hydration += random.uniform(0.05, 0.3)
    return tiles


def build_initial_state(width: int = 10, height: int = 10) -> GameState:
    tiles = wfc_like_map(width, height)
    player = (width // 2, height // 2)
    depot_pos = player
    depot_tile = tiles[depot_pos[0]][depot_pos[1]]
    depot_tile.kind = "flat"
    depot_tile.trench = False
    depot_tile.elevation = 1.0
    depot_tile.well_output = 0.0
    depot_tile.depot = True
    return GameState(width=width, height=height, tiles=tiles, player=player)


def render(state: GameState) -> None:
    print("\n" * 2)
    phase = "Night" if state.heat < 1.0 else "Day"
    print(f"Day {state.day} [{phase}] Heat {state.heat:.2f}  Dust in {state.dust_timer}  Rain in {state.rain_timer} ({'on' if state.raining else 'off'})")
    inv = state.inventory
    print(f"Water {inv['water']:.1f} | Scrap {inv['scrap']} | Seeds {inv['seeds']} | Biomass {inv['biomass']}")
    print("Legend: @ you, D depot, C cistern, N condenser, F planter, = trench, ~ wet, : damp")
    print("Map:")
    for y in range(state.height):
        row = []
        for x in range(state.width):
            pos = (x, y)
            tile = state.tiles[x][y]
            structure = state.structures.get(pos)
            ttype = TILE_TYPES[tile.kind]
            symbol = ttype.char
            if tile.hydration >= 1.0:
                symbol = "~"
            elif tile.hydration >= 0.5:
                symbol = ":"
            if tile.trench:
                symbol = "="
            if tile.depot:
                symbol = "D"
            if structure:
                symbol = {"cistern": "C", "condenser": "N", "planter": "F"}.get(structure.kind, "?")
            if state.player == pos:
                symbol = "@"
            row.append(symbol)
        print("".join(row))
    if state.messages:
        print("Events:")
        for msg in state.messages[-5:]:
            print(f"- {msg}")


def parse_command(raw: str) -> Tuple[str, List[str]]:
    parts = raw.strip().lower().split()
    if not parts:
        return "", []
    return parts[0], parts[1:]


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
    if tile.trench:
        state.messages.append("Already trenched.")
        return
    tile.trench = True
    tile.hydration = max(tile.hydration - 0.1, 0.0)
    state.messages.append("Dug a trench; flow improves, evap drops here.")


def lower_ground(state: GameState) -> None:
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.elevation <= 0.2:
        state.messages.append("Ground is already low.")
        return
    tile.elevation = max(0.1, tile.elevation - 0.2)
    state.messages.append(f"Lowered ground to elev {tile.elevation:.2f}.")


def raise_ground(state: GameState) -> None:
    if state.inventory.get("scrap", 0) < 1:
        state.messages.append("Need 1 scrap to raise ground.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.elevation >= 2.5:
        state.messages.append("Ground too high already.")
        return
    state.inventory["scrap"] -= 1
    tile.elevation = min(2.5, tile.elevation + 0.2)
    state.messages.append(f"Raised ground (cost 1 scrap) to elev {tile.elevation:.2f}.")


def build_structure(state: GameState, kind: str) -> None:
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
        state.inventory[resource] -= needed
    state.structures[pos] = Structure(kind=kind)
    state.messages.append(f"Built {kind} at {pos}.")


def collect_water(state: GameState) -> None:
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.depot:
        state.inventory["water"] += 3
        state.inventory["scrap"] += 3
        state.inventory["seeds"] += 1
        state.messages.append("Depot resupply: +3 water, +3 scrap, +1 seeds.")
        return
    available = tile.hydration
    if available <= 0.05:
        state.messages.append("No water to collect here.")
        return
    gathered = min(1.0, available)
    tile.hydration = max(tile.hydration - gathered, 0.0)
    state.inventory["water"] += gathered
    state.messages.append(f"Collected {gathered:.1f} water.")


def pour_water(state: GameState, amount: float) -> None:
    if amount <= 0:
        state.messages.append("Pour a positive amount.")
        return
    if state.inventory["water"] < amount:
        state.messages.append("Not enough water carried.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    tile.hydration += amount
    state.inventory["water"] -= amount
    state.messages.append(f"Poured {amount:.1f} water into soil.")


def tick_structures(state: GameState, heat: float, dust: bool) -> None:
    for pos, structure in list(state.structures.items()):
        tile = state.tiles[pos[0]][pos[1]]
        if dust:
            structure.hp -= 1
            if structure.hp <= 0:
                state.messages.append(f"{structure.kind} at {pos} collapsed in the dust front!")
                del state.structures[pos]
                continue
        if structure.kind == "condenser":
            tile.hydration += 0.25
        elif structure.kind == "cistern":
            if tile.hydration > 0.4 and structure.stored < 5.0:
                transfer = min(0.4, tile.hydration, 5.0 - structure.stored)
                tile.hydration -= transfer
                structure.stored += transfer
            loss = 0.03 * heat
            drained = min(structure.stored, loss)
            structure.stored -= drained
            tile.hydration += drained * 0.5
        elif structure.kind == "planter":
            if tile.hydration >= 0.8:
                structure.growth += 0.25
            else:
                structure.growth = max(structure.growth - 0.1, 0.0)
            if structure.growth >= 1.0:
                structure.growth = 0.0
                state.inventory["biomass"] += 1
                state.inventory["seeds"] += 1
                tile.hydration = max(tile.hydration - 0.3, 0.0)
                state.messages.append(f"Biomass harvested at {pos}! (Total {state.inventory['biomass']})")


def simulate_tick(state: GameState) -> None:
    # Heat rises slightly during the day, resets at night.
    state.turn_in_day += 1
    DAY_LENGTH = 12
    daytime = state.turn_in_day % DAY_LENGTH
    # Peak heat midday, cooler at night.
    day_factor = (1 - abs((daytime / (DAY_LENGTH - 1)) * 2 - 1))  # 0 at edges, 1 at midpoint
    state.heat = 0.8 + 0.6 * day_factor

    state.dust_timer -= 1
    dust_front = False
    if state.dust_timer <= 0:
        dust_front = True
        state.messages.append("Dust front hits! Evap spikes and structures take damage.")
        state.dust_timer = random.randint(8, 12)

    # Rain scheduling
    state.rain_timer -= 1
    if state.raining:
        if state.rain_timer <= 0:
            state.raining = False
            state.rain_timer = random.randint(12, 20)
            state.messages.append("Rain fades.")
    else:
        if state.rain_timer <= 0:
            state.raining = True
            state.rain_timer = random.randint(3, 5)
            state.messages.append("Rain arrives! Springs surge.")

    tick_structures(state, state.heat, dust_front)

    flows: Dict[Point, float] = {}
    surfaces: Dict[Point, float] = {}
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            # Wells feed water.
            if tile.well_output > 0:
                gain = tile.well_output * (1.5 if state.raining else 1.0)
                tile.hydration += gain

            evap = ttype.evap * state.heat
            if tile.trench:
                evap *= 0.85
            if (x, y) in state.structures and state.structures[(x, y)].kind == "cistern":
                evap *= 0.4

            base_loss = evap - ttype.retention
            tile.hydration = max(tile.hydration - base_loss, 0.0)

            effective_elev = tile.elevation - (0.15 if tile.trench else 0.0)
            surfaces[(x, y)] = effective_elev + tile.hydration

    # Flow based on surface height (elevation + water depth)
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            surface = surfaces[(x, y)]
            nbrs = neighbors(x, y, state.width, state.height)
            lower_neighbors = []
            total_diff = 0.0
            for nx, ny in nbrs:
                n_surface = surfaces[(nx, ny)]
                diff = surface - n_surface
                if diff > 0.05:
                    lower_neighbors.append(((nx, ny), diff))
                    total_diff += diff
            if not lower_neighbors or tile.hydration <= 0:
                continue
            transferable = tile.hydration * 0.5  # only move part each tick
            for (nx, ny), diff in lower_neighbors:
                portion = transferable * (diff / total_diff)
                flows[(nx, ny)] = flows.get((nx, ny), 0.0) + portion
                tile.hydration -= portion

    for (nx, ny), amt in flows.items():
        state.tiles[nx][ny].hydration += amt


def end_day(state: GameState) -> None:
    state.day += 1
    state.turn_in_day = 0
    state.heat = 1.0
    state.messages.append("Night falls. Heat resets; small evap recovery.")
    for _ in range(4):
        simulate_tick(state)


def show_status(state: GameState) -> None:
    inv = state.inventory
    cisterns = [s for s in state.structures.values() if s.kind == "cistern"]
    stored = sum(s.stored for s in cisterns)
    print(f"Inventory: water {inv['water']:.1f}, scrap {inv['scrap']}, seeds {inv['seeds']}, biomass {inv['biomass']}")
    print(f"Cistern storage: {stored:.1f} across {len(cisterns)} cistern(s).")


def survey_tile(state: GameState) -> None:
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))
    desc = [
        f"Tile {x},{y}",
        f"type={tile.kind}",
        f"elev={tile.elevation:.2f}",
        f"hydr={tile.hydration:.2f}",
    ]
    if tile.well_output > 0:
        desc.append(f"well={tile.well_output:.2f}/t")
    if tile.trench:
        desc.append("trench")
    if structure:
        desc.append(f"struct={structure.kind}")
    state.messages.append("Survey: " + " | ".join(desc))
    print(state.messages[-1])


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    if cmd in ("w", "a", "s", "d"):
        move_player(state, cmd)
    elif cmd == "dig":
        dig_trench(state)
    elif cmd == "lower":
        lower_ground(state)
    elif cmd == "raise":
        raise_ground(state)
    elif cmd == "build":
        if not args:
            state.messages.append("Usage: build cistern|condenser|planter")
        else:
            build_structure(state, args[0])
    elif cmd == "collect":
        collect_water(state)
    elif cmd == "pour":
        if not args:
            state.messages.append("Usage: pour <amount>")
        else:
            try:
                amount = float(args[0])
                pour_water(state, amount)
            except ValueError:
                state.messages.append("Amount must be a number.")
    elif cmd == "status":
        show_status(state)
    elif cmd == "survey":
        survey_tile(state)
    elif cmd == "end":
        end_day(state)
    elif cmd == "help":
        print("Commands: w/a/s/d, dig, lower, raise, build <type>, collect, pour <amt>, survey, status, end, quit")
    elif cmd == "quit":
        return True
    else:
        state.messages.append("Unknown command. Type 'help' for options.")
    return False


def main() -> None:
    random.seed()
    state = build_initial_state()
    state.messages.append("You arrive with a cart of scrap, a few seeds, and two canteens of water.")
    state.messages.append("Find water, trap it, and grow biomass.")
    while True:
        render(state)
        raw = input("\nCommand> ")
        cmd, args = parse_command(raw)
        if not cmd:
            continue
        quit_now = handle_command(state, cmd, args)
        if quit_now:
            print("Exiting. Thanks for playing the prototype.")
            break
        if cmd != "status" and cmd != "help":
            simulate_tick(state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
