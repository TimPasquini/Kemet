"""
Kemet – Desert Farm Prototype
Turn-based ASCII simulation: explore, capture water, build, and green a patch.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Union

Point = Tuple[int, int]

# Game constants - simulation parameters
CONDENSER_OUTPUT = 0.25
PLANTER_GROWTH_RATE = 0.25
PLANTER_GROWTH_THRESHOLD = 1.0
PLANTER_WATER_COST = 0.3
TRENCH_EVAP_REDUCTION = 0.85
CISTERN_EVAP_REDUCTION = 0.4
CISTERN_CAPACITY = 5.0
CISTERN_TRANSFER_RATE = 0.4
CISTERN_LOSS_RATE = 0.03
CISTERN_LOSS_RECOVERY = 0.5
FLOW_TRANSFER_RATE = 0.5
ELEVATION_FLOW_THRESHOLD = 0.05

# Day/night cycle constants
DAY_LENGTH = 12
HEAT_MIN = 0.6
HEAT_MAX = 1.4
HEAT_NIGHT_THRESHOLD = 0.9

# Input validation limits
MAX_POUR_AMOUNT = 100.0
MAX_ELEVATION = 2.5
MIN_ELEVATION = 0.2

# Depot resupply amounts
DEPOT_WATER_AMOUNT = 3.0
DEPOT_SCRAP_AMOUNT = 3
DEPOT_SEEDS_AMOUNT = 1


@dataclass
class TileType:
    """Defines the properties of a terrain type."""
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
    """Represents a single map tile with terrain and water properties."""
    kind: str
    hydration: float = 0.0
    trench: bool = False
    elevation: float = 0.0
    well_output: float = 0.0
    depot: bool = False


@dataclass
class Structure:
    """Represents a player-built structure on a tile."""
    kind: str
    hp: int = 3
    stored: float = 0.0
    growth: float = 0.0


STRUCTURE_COSTS: Dict[str, Dict[str, Union[int, float]]] = {
    "cistern": {"scrap": 3},
    "condenser": {"scrap": 2},
    "planter": {"scrap": 1, "seeds": 1},
}


@dataclass
class GameState:
    """Main game state container."""
    width: int
    height: int
    tiles: List[List[Tile]]
    structures: Dict[Point, Structure] = field(default_factory=dict)
    player: Point = (0, 0)
    inventory: Dict[str, Union[int, float]] = field(
        default_factory=lambda: {"water": 2.0, "scrap": 6, "seeds": 2, "biomass": 0}
    )
    day: int = 1
    turn_in_day: int = 0
    heat: float = 1.0
    rain_timer: int = 12
    raining: bool = False
    messages: List[str] = field(default_factory=list)


def clamp(val: float, low: float, high: float) -> float:
    """Clamp a value between low and high bounds."""
    return max(low, min(high, val))


def neighbors(x: int, y: int, width: int, height: int) -> List[Point]:
    """Return list of valid orthogonal neighbors for a given position."""
    options = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            options.append((nx, ny))
    return options


def wfc_like_map(width: int, height: int) -> List[List[Tile]]:
    """
    Generate a map using wave function collapse-like algorithm.
    
    Creates terrain with adjacency preferences to form plausible biomes.
    Seeds 3-4 wells with varying water output rates.
    """
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    # Initialize with flat tiles to avoid None typing issues
    tiles: List[List[Tile]] = [
        [Tile("flat", elevation=1.0) for _ in range(height)] 
        for _ in range(width)
    ]
    
    positions = [(x, y) for x in range(width) for y in range(height)]
    random.shuffle(positions)

    for x, y in positions:
        neighbor_types = [
            tiles[nx][ny].kind 
            for nx, ny in neighbors(x, y, width, height)
        ]
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

    # Seed wells (fixed sources) and wet wadis
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
    """Create initial game state with generated map and player spawn."""
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
    """Render the game state to console (ASCII mode)."""
    print("\n" * 2)
    phase = "Night" if state.heat < HEAT_NIGHT_THRESHOLD else "Day"
    print(f"Day {state.day} [{phase}] Heat {state.heat:.2f}  Rain in {state.rain_timer} ({'on' if state.raining else 'off'})")
    inv = state.inventory
    print(f"Water {inv['water']:.1f} | Scrap {inv['scrap']} | Seeds {inv['seeds']} | Biomass {inv['biomass']}")
    print("Legend: @ you, D depot, C cistern, N condenser, P planter, = trench, ~ wet, : damp")
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
                symbol = {"cistern": "C", "condenser": "N", "planter": "P"}.get(structure.kind, "?")
            if state.player == pos:
                symbol = "@"
            row.append(symbol)
        print("".join(row))
    if state.messages:
        print("Events:")
        for msg in state.messages[-5:]:
            print(f"- {msg}")


def parse_command(raw: str) -> Tuple[str, List[str]]:
    """Parse user input into command and arguments."""
    parts = raw.strip().lower().split()
    if not parts:
        return "", []
    return parts[0], parts[1:]


def move_player(state: GameState, direction: str) -> None:
    """
    Move player in the specified direction (w/a/s/d).
    
    Blocks movement into rocks or out of bounds.
    """
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
    """Dig a trench on current tile to improve water flow and reduce evaporation."""
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.trench:
        state.messages.append("Already trenched.")
        return
    tile.trench = True
    tile.hydration = max(tile.hydration - 0.1, 0.0)
    state.messages.append("Dug a trench; flow improves, evap drops here.")


def lower_ground(state: GameState) -> None:
    """Lower ground elevation on current tile."""
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.elevation <= MIN_ELEVATION:
        state.messages.append("Ground is already low.")
        return
    tile.elevation = max(MIN_ELEVATION, tile.elevation - 0.2)
    state.messages.append(f"Lowered ground to elev {tile.elevation:.2f}.")


def raise_ground(state: GameState) -> None:
    """Raise ground elevation on current tile (costs 1 scrap)."""
    if state.inventory.get("scrap", 0) < 1:
        state.messages.append("Need 1 scrap to raise ground.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.elevation >= MAX_ELEVATION:
        state.messages.append("Ground too high already.")
        return
    state.inventory["scrap"] = int(state.inventory["scrap"]) - 1
    tile.elevation = min(MAX_ELEVATION, tile.elevation + 0.2)
    state.messages.append(f"Raised ground (cost 1 scrap) to elev {tile.elevation:.2f}.")


def build_structure(state: GameState, kind: str) -> None:
    """
    Build a structure on current tile.
    
    Checks resource costs and tile availability before building.
    """
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
    state.messages.append(f"Built {kind} at {pos}.")


def collect_water(state: GameState) -> None:
    """
    Collect water from current tile into inventory.
    
    Depot tiles provide unlimited resources for testing.
    """
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.depot:
        state.inventory["water"] = float(state.inventory["water"]) + DEPOT_WATER_AMOUNT
        state.inventory["scrap"] = int(state.inventory["scrap"]) + DEPOT_SCRAP_AMOUNT
        state.inventory["seeds"] = int(state.inventory["seeds"]) + DEPOT_SEEDS_AMOUNT
        state.messages.append(f"Depot resupply: +{DEPOT_WATER_AMOUNT} water, +{DEPOT_SCRAP_AMOUNT} scrap, +{DEPOT_SEEDS_AMOUNT} seeds.")
        return
    available = tile.hydration
    if available <= 0.05:
        state.messages.append("No water to collect here.")
        return
    gathered = min(1.0, available)
    tile.hydration = max(tile.hydration - gathered, 0.0)
    state.inventory["water"] = float(state.inventory["water"]) + gathered
    state.messages.append(f"Collected {gathered:.1f} water.")


def pour_water(state: GameState, amount: float) -> None:
    """Pour water from inventory onto current tile."""
    if amount <= 0 or amount > MAX_POUR_AMOUNT:
        state.messages.append(f"Pour between 0.1 and {MAX_POUR_AMOUNT}.")
        return
    if state.inventory["water"] < amount:
        state.messages.append("Not enough water carried.")
        return
    tile = state.tiles[state.player[0]][state.player[1]]
    tile.hydration += amount
    state.inventory["water"] = float(state.inventory["water"]) - amount
    state.messages.append(f"Poured {amount:.1f} water into soil.")


def tick_structures(state: GameState, heat: float) -> None:
    """
    Update all structures for one simulation tick.
    
    - Condensers produce water
    - Cisterns store and slowly leak water
    - Planters grow biomass when hydrated
    """
    for pos, structure in list(state.structures.items()):
        tile = state.tiles[pos[0]][pos[1]]
        if structure.kind == "condenser":
            tile.hydration += CONDENSER_OUTPUT
        elif structure.kind == "cistern":
            if tile.hydration > CISTERN_TRANSFER_RATE and structure.stored < CISTERN_CAPACITY:
                transfer = min(CISTERN_TRANSFER_RATE, tile.hydration, CISTERN_CAPACITY - structure.stored)
                tile.hydration -= transfer
                structure.stored += transfer
            loss = CISTERN_LOSS_RATE * heat
            drained = min(structure.stored, loss)
            structure.stored -= drained
            tile.hydration += drained * CISTERN_LOSS_RECOVERY
        elif structure.kind == "planter":
            if tile.hydration >= 0.8:
                structure.growth += PLANTER_GROWTH_RATE
            else:
                structure.growth = max(structure.growth - 0.1, 0.0)
            if structure.growth >= PLANTER_GROWTH_THRESHOLD:
                structure.growth = 0.0
                state.inventory["biomass"] = int(state.inventory["biomass"]) + 1
                state.inventory["seeds"] = int(state.inventory["seeds"]) + 1
                tile.hydration = max(tile.hydration - PLANTER_WATER_COST, 0.0)
                state.messages.append(f"Biomass harvested at {pos}! (Total {state.inventory['biomass']})")


def simulate_tick(state: GameState) -> None:
    """
    Advance simulation by one tick.
    
    Updates heat cycle, handles rain, ticks structures,
    applies evaporation, and simulates water flow.
    """
    # Heat cycle: varies from HEAT_MIN at night to HEAT_MAX at midday
    state.turn_in_day += 1
    daytime = state.turn_in_day % DAY_LENGTH
    # day_factor: 0 at dawn/dusk, 1 at midday
    day_factor = (1 - abs((daytime / (DAY_LENGTH - 1)) * 2 - 1))
    state.heat = HEAT_MIN + (HEAT_MAX - HEAT_MIN) * day_factor

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

    tick_structures(state, state.heat)

    # Calculate surface heights for flow simulation
    surfaces: Dict[Point, float] = {}
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            # Wells feed water
            if tile.well_output > 0:
                gain = tile.well_output * (1.5 if state.raining else 1.0)
                tile.hydration += gain

            # Apply evaporation
            evap = ttype.evap * state.heat
            if tile.trench:
                evap *= TRENCH_EVAP_REDUCTION
            if (x, y) in state.structures and state.structures[(x, y)].kind == "cistern":
                evap *= CISTERN_EVAP_REDUCTION

            base_loss = evap - ttype.retention
            tile.hydration = max(tile.hydration - base_loss, 0.0)

            # Calculate effective elevation for flow
            effective_elev = tile.elevation - (0.15 if tile.trench else 0.0)
            surfaces[(x, y)] = effective_elev + tile.hydration

    # Flow based on surface height (elevation + water depth)
    flows: Dict[Point, float] = {}
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
                if diff > ELEVATION_FLOW_THRESHOLD:
                    lower_neighbors.append(((nx, ny), diff))
                    total_diff += diff
            if not lower_neighbors or tile.hydration <= 0:
                continue
            
            # Transfer water proportionally to height differences
            transferable = tile.hydration * FLOW_TRANSFER_RATE
            total_transferred = 0.0
            for (nx, ny), diff in lower_neighbors:
                portion = transferable * (diff / total_diff)
                flows[(nx, ny)] = flows.get((nx, ny), 0.0) + portion
                total_transferred += portion
            # Deduct all transferred water at once to prevent negative values
            tile.hydration -= total_transferred

    # Apply accumulated flows
    for (nx, ny), amt in flows.items():
        state.tiles[nx][ny].hydration += amt


def end_day(state: GameState) -> None:
    """Advance to next day and run several simulation ticks."""
    state.day += 1
    state.turn_in_day = 0
    state.heat = 1.0
    state.messages.append("Night falls. Heat resets; small evap recovery.")
    for _ in range(4):
        simulate_tick(state)


def show_status(state: GameState) -> None:
    """Display current inventory and cistern storage."""
    inv = state.inventory
    cisterns = [s for s in state.structures.values() if s.kind == "cistern"]
    stored = sum(s.stored for s in cisterns)
    state.messages.append(f"Inv: water {inv['water']:.1f}, scrap {inv['scrap']}, seeds {inv['seeds']}, biomass {inv['biomass']}")
    state.messages.append(f"Cisterns: {stored:.1f} stored across {len(cisterns)} cistern(s)")


def survey_tile(state: GameState) -> None:
    """Display detailed information about current tile."""
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
        if structure.kind == "cistern":
            desc.append(f"stored={structure.stored:.2f}")
        elif structure.kind == "planter":
            desc.append(f"growth={structure.growth:.2f}")
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """
    Process a player command.
    
    Returns True if the game should quit, False otherwise.
    """
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
        state.messages.append("Commands: w/a/s/d, dig, lower, raise, build <type>, collect, pour <amt>, survey, status, end, quit")
    elif cmd == "quit":
        return True
    else:
        state.messages.append("Unknown command. Type 'help' for options.")
    return False


def main() -> None:
    """Main game loop for ASCII mode."""
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
