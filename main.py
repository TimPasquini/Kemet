"""
Kemet – Desert Farm Prototype
Turn-based ASCII simulation: explore, capture water, build, and green a patch.

Updated to use fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Union

from ground import (
    TerrainColumn,
    SurfaceTraits,
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
    MATERIAL_LIBRARY,
)
from water import (
    WaterColumn,
    simulate_vertical_seepage,
    calculate_surface_flow,
    calculate_subsurface_flow,
    apply_flows,
)

Point = Tuple[int, int]

# Game constants - simulation parameters
CONDENSER_OUTPUT = 2  # Units of water per tick (0.2L)
PLANTER_GROWTH_RATE = 25  # Growth points per tick (out of 100)
PLANTER_GROWTH_THRESHOLD = 100
PLANTER_WATER_COST = 3  # Units of water consumed on harvest
TRENCH_EVAP_REDUCTION = 85  # Percentage (85 = 0.85x)
CISTERN_EVAP_REDUCTION = 40  # Percentage (40 = 0.40x)
CISTERN_CAPACITY = 500  # Units (50L)
CISTERN_TRANSFER_RATE = 40  # Units per tick
CISTERN_LOSS_RATE = 3  # Units per tick at max heat
CISTERN_LOSS_RECOVERY = 50  # Percentage returned to surface

# Day/night cycle constants
DAY_LENGTH = 12
HEAT_MIN = 60  # Percentage (60 = 0.6x)
HEAT_MAX = 140  # Percentage (140 = 1.4x)
HEAT_NIGHT_THRESHOLD = 90  # Below this is "night"

# Input validation limits
MAX_POUR_AMOUNT = 1000  # 100L
MIN_LAYER_THICKNESS = 1  # Minimum depth before exposing layer below

# Depot resupply amounts
DEPOT_WATER_AMOUNT = 30  # 3L
DEPOT_SCRAP_AMOUNT = 3
DEPOT_SEEDS_AMOUNT = 1


@dataclass
class TileType:
    """Defines the properties of a biome type (for generation and display)."""
    name: str
    char: str
    evap: int  # Base evaporation percentage
    capacity: int  # Not used in new system (kept for compatibility)
    retention: int  # Percentage of evaporation retained


TILE_TYPES: Dict[str, TileType] = {
    "dune": TileType("dune", ".", evap=12, capacity=60, retention=5),
    "flat": TileType("flat", ",", evap=9, capacity=90, retention=8),
    "wadi": TileType("wadi", "w", evap=5, capacity=140, retention=20),
    "rock": TileType("rock", "^", evap=6, capacity=50, retention=2),
    "salt": TileType("salt", "_", evap=14, capacity=70, retention=3),
}


@dataclass
class Tile:
    """Represents a single map tile with layered terrain and water."""
    kind: str              # Biome type (affects generation, visuals)
    terrain: TerrainColumn
    water: WaterColumn
    surface: SurfaceTraits
    
    # Tile-level properties
    well_output: int = 0  # Water units produced per tick
    depot: bool = False
    
    # Backwards compatibility properties
    @property
    def elevation(self) -> float:
        """Surface elevation in meters (for display/compatibility)."""
        return units_to_meters(self.terrain.get_surface_elevation())
    
    @property
    def hydration(self) -> float:
        """Total water in liters (for display/compatibility)."""
        return self.water.total_water() / 10.0  # 10 units = 1L
    
    @property
    def trench(self) -> bool:
        """Trench status (for compatibility)."""
        return self.surface.has_trench
    
    @trench.setter
    def trench(self, value: bool) -> None:
        """Set trench status."""
        self.surface.has_trench = value


@dataclass
class Structure:
    """Represents a player-built structure on a tile."""
    kind: str
    hp: int = 3
    stored: int = 0  # Water storage in units
    growth: int = 0  # Growth progress (0-100)


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
        default_factory=lambda: {"water": 20, "scrap": 6, "seeds": 2, "biomass": 0}
    )
    day: int = 1
    turn_in_day: int = 0
    heat: int = 100  # Percentage
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
    Uses fixed-layer terrain system.
    """
    base_weights = {"dune": 4, "flat": 5, "wadi": 2, "rock": 2, "salt": 2}
    adjacency = {
        "dune": {"dune": 3, "flat": 2, "rock": 1},
        "flat": {"flat": 3, "wadi": 2, "dune": 2, "salt": 1},
        "wadi": {"flat": 3, "wadi": 2, "dune": 1},
        "rock": {"rock": 2, "dune": 2, "flat": 1},
        "salt": {"salt": 2, "flat": 2, "dune": 1},
    }

    # Generate bedrock base (around -2m to -2.5m below sea level)
    bedrock_base = elevation_to_units(random.uniform(-2.5, -2.0))
    
    # Initialize with flat tiles
    tiles: List[List[Tile]] = []
    for x in range(width):
        column = []
        for y in range(height):
            terrain = create_default_terrain(bedrock_base, elevation_to_units(1.0))
            water = WaterColumn()
            surface = SurfaceTraits()
            tile = Tile(kind="flat", terrain=terrain, water=water, surface=surface)
            column.append(tile)
        tiles.append(column)
    
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
        
        # Create terrain based on biome type (varying soil depth)
        depth_map = {
            "dune": random.uniform(1.5, 2.5),
            "flat": random.uniform(1.0, 2.0),
            "wadi": random.uniform(0.5, 1.2),
            "rock": random.uniform(0.2, 0.6),
            "salt": random.uniform(0.8, 1.5),
        }
        
        # Add slight bedrock variation
        bedrock_elev = bedrock_base + elevation_to_units(random.uniform(-0.3, 0.3))
        total_soil = elevation_to_units(depth_map[choice])
        terrain = create_default_terrain(bedrock_elev, total_soil)
        water = WaterColumn()
        surface = SurfaceTraits()
        tiles[x][y] = Tile(kind=choice, terrain=terrain, water=water, surface=surface)

    # Seed wells (fixed sources)
    wells = random.randint(3, 4)
    for _ in range(wells):
        rx, ry = random.randrange(width), random.randrange(height)
        tiles[rx][ry].kind = "wadi"
        # Varying rates: seep (1-2 units/tick) vs spring (3-6 units/tick)
        tiles[rx][ry].well_output = random.choice([
            random.randint(1, 2),
            random.randint(3, 6)
        ])
        # Start wells with some subsurface water in regolith
        tiles[rx][ry].water.regolith_water = 50
        tiles[rx][ry].water.surface_water = 40
    
    # Add initial water to wadis
    for x in range(width):
        for y in range(height):
            if tiles[x][y].kind == "wadi":
                tiles[x][y].water.surface_water += random.randint(5, 30)
    
    return tiles


def build_initial_state(width: int = 10, height: int = 10) -> GameState:
    """Create initial game state with generated map and player spawn."""
    tiles = wfc_like_map(width, height)
    player = (width // 2, height // 2)
    depot_pos = player
    depot_tile = tiles[depot_pos[0]][depot_pos[1]]
    
    # Set up depot tile (flat, accessible terrain)
    depot_tile.kind = "flat"
    depot_tile.surface.has_trench = False
    depot_tile.terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    depot_tile.well_output = 0
    depot_tile.depot = True
    
    return GameState(width=width, height=height, tiles=tiles, player=player)


def render(state: GameState) -> None:
    """Render the game state to console (ASCII mode)."""
    print("\n" * 2)
    phase = "Night" if state.heat < HEAT_NIGHT_THRESHOLD else "Day"
    print(f"Day {state.day} [{phase}] Heat {state.heat}%  Rain in {state.rain_timer} ({'on' if state.raining else 'off'})")
    inv = state.inventory
    print(f"Water {inv['water']/10:.1f}L | Scrap {inv['scrap']} | Seeds {inv['seeds']} | Biomass {inv['biomass']}")
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
            
            # Water visualization
            total_water = tile.water.total_water()
            if total_water >= 100:  # 10L
                symbol = "~"
            elif total_water >= 50:  # 5L
                symbol = ":"
            
            if tile.surface.has_trench:
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
    """Move player in the specified direction (w/a/s/d)."""
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
    """Dig a trench on current tile."""
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.surface.has_trench:
        state.messages.append("Already trenched.")
        return
    tile.surface.has_trench = True
    # Remove some surface water when digging
    tile.water.surface_water = max(tile.water.surface_water - 10, 0)
    state.messages.append("Dug a trench; flow improves, evap drops here.")


def lower_ground(state: GameState) -> None:
    """Lower ground elevation on current tile by removing topsoil."""
    tile = state.tiles[state.player[0]][state.player[1]]
    
    # Try to remove from topsoil first
    if tile.terrain.topsoil_depth > MIN_LAYER_THICKNESS:
        removed = tile.terrain.remove_material_from_layer(SoilLayer.TOPSOIL, 2)  # Remove ~20cm
        state.messages.append(f"Removed {units_to_meters(removed):.2f}m topsoil. Elev: {tile.elevation:.2f}m")
    elif tile.terrain.eluviation_depth > MIN_LAYER_THICKNESS:
        removed = tile.terrain.remove_material_from_layer(SoilLayer.ELUVIATION, 2)
        state.messages.append(f"Removed {units_to_meters(removed):.2f}m eluviation. Elev: {tile.elevation:.2f}m")
    elif tile.terrain.subsoil_depth > MIN_LAYER_THICKNESS:
        removed = tile.terrain.remove_material_from_layer(SoilLayer.SUBSOIL, 2)
        state.messages.append(f"Removed {units_to_meters(removed):.2f}m subsoil. Elev: {tile.elevation:.2f}m")
    else:
        state.messages.append("Can't dig further - regolith/bedrock too close!")


def raise_ground(state: GameState) -> None:
    """Raise ground elevation on current tile (costs 1 scrap)."""
    if state.inventory.get("scrap", 0) < 1:
        state.messages.append("Need 1 scrap to raise ground.")
        return
    
    tile = state.tiles[state.player[0]][state.player[1]]
    state.inventory["scrap"] = int(state.inventory["scrap"]) - 1
    
    # Add to topsoil layer
    tile.terrain.add_material_to_layer(SoilLayer.TOPSOIL, 2)  # Add ~20cm
    state.messages.append(f"Added topsoil (cost 1 scrap). Elev: {tile.elevation:.2f}m")


def build_structure(state: GameState, kind: str) -> None:
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


def collect_water(state: GameState) -> None:
    """Collect water from current tile into inventory."""
    tile = state.tiles[state.player[0]][state.player[1]]
    if tile.depot:
        state.inventory["water"] = int(state.inventory["water"]) + DEPOT_WATER_AMOUNT
        state.inventory["scrap"] = int(state.inventory["scrap"]) + DEPOT_SCRAP_AMOUNT
        state.inventory["seeds"] = int(state.inventory["seeds"]) + DEPOT_SEEDS_AMOUNT
        state.messages.append(f"Depot resupply: +{DEPOT_WATER_AMOUNT/10:.1f}L water, +{DEPOT_SCRAP_AMOUNT} scrap, +{DEPOT_SEEDS_AMOUNT} seeds.")
        return
    
    available = tile.water.surface_water
    if available <= 5:  # Less than 0.5L
        state.messages.append("No water to collect here.")
        return
    
    gathered = min(100, available)  # Collect up to 10L
    tile.water.surface_water -= gathered
    state.inventory["water"] = int(state.inventory["water"]) + gathered
    state.messages.append(f"Collected {gathered/10:.1f}L water.")


def pour_water(state: GameState, amount: float) -> None:
    """Pour water from inventory onto current tile."""
    amount_units = int(amount * 10)  # Convert liters to units
    
    if amount_units <= 0 or amount_units > MAX_POUR_AMOUNT:
        state.messages.append(f"Pour between 0.1L and {MAX_POUR_AMOUNT/10}L.")
        return
    if state.inventory["water"] < amount_units:
        state.messages.append("Not enough water carried.")
        return
    
    tile = state.tiles[state.player[0]][state.player[1]]
    tile.water.surface_water += amount_units
    state.inventory["water"] = int(state.inventory["water"]) - amount_units
    state.messages.append(f"Poured {amount:.1f}L water into soil.")


def tick_structures(state: GameState, heat: int) -> None:
    """Update all structures for one simulation tick."""
    for pos, structure in list(state.structures.items()):
        tile = state.tiles[pos[0]][pos[1]]
        
        if structure.kind == "condenser":
            tile.water.surface_water += CONDENSER_OUTPUT
            
        elif structure.kind == "cistern":
            # Transfer surface water into cistern storage
            if tile.water.surface_water > CISTERN_TRANSFER_RATE and structure.stored < CISTERN_CAPACITY:
                transfer = min(CISTERN_TRANSFER_RATE, tile.water.surface_water, CISTERN_CAPACITY - structure.stored)
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
            if total_water >= 80:  # Need 8L of water
                structure.growth += PLANTER_GROWTH_RATE
                if structure.growth > PLANTER_GROWTH_THRESHOLD:
                    structure.growth = PLANTER_GROWTH_THRESHOLD
            else:
                structure.growth = max(structure.growth - 10, 0)
            
            if structure.growth >= PLANTER_GROWTH_THRESHOLD:
                structure.growth = 0
                state.inventory["biomass"] = int(state.inventory["biomass"]) + 1
                state.inventory["seeds"] = int(state.inventory["seeds"]) + 1
                tile.water.surface_water = max(tile.water.surface_water - PLANTER_WATER_COST, 0)
                
                # Add organics layer on harvest
                tile.terrain.add_material_to_layer(SoilLayer.ORGANICS, 1)
                
                state.messages.append(f"Biomass harvested at {pos}! (Total {state.inventory['biomass']})")


def simulate_tick(state: GameState) -> None:
    """Advance simulation by one tick."""
    # Heat cycle (percentage: 60-140)
    state.turn_in_day += 1
    daytime = state.turn_in_day % DAY_LENGTH
    day_factor = (1 - abs((daytime / (DAY_LENGTH - 1)) * 2 - 1))
    state.heat = HEAT_MIN + int((HEAT_MAX - HEAT_MIN) * day_factor)

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

    # Process each tile
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]
            
            # Wells feed water into subsurface (regolith layer)
            if tile.well_output > 0:
                gain = tile.well_output
                if state.raining:
                    gain = (gain * 150) // 100  # 1.5x during rain
                tile.water.regolith_water += gain

            # Vertical seepage (surface <-> subsurface)
            simulate_vertical_seepage(tile.terrain, tile.water)

            # Apply evaporation to surface water only
            evap = (ttype.evap * state.heat) // 100  # Scale by heat
            if tile.surface.has_trench:
                evap = (evap * TRENCH_EVAP_REDUCTION) // 100
            if (x, y) in state.structures and state.structures[(x, y)].kind == "cistern":
                evap = (evap * CISTERN_EVAP_REDUCTION) // 100

            retention = (ttype.retention * evap) // 100
            net_loss = evap - retention
            tile.water.surface_water = max(tile.water.surface_water - net_loss, 0)

    # Horizontal flow (surface and subsurface)
    tiles_data = [
        [(state.tiles[x][y].terrain, state.tiles[x][y].water) for y in range(state.height)]
        for x in range(state.width)
    ]
    
    trench_map = {
        (x, y): state.tiles[x][y].surface.has_trench
        for x in range(state.width)
        for y in range(state.height)
    }
    
    surface_flows = calculate_surface_flow(tiles_data, state.width, state.height, trench_map)
    subsurface_flows = calculate_subsurface_flow(tiles_data, state.width, state.height)
    apply_flows(tiles_data, surface_flows, subsurface_flows)


def end_day(state: GameState) -> None:
    """Advance to next day and run several simulation ticks."""
    state.day += 1
    state.turn_in_day = 0
    state.heat = 100
    state.messages.append("Night falls. Heat resets; small evap recovery.")
    for _ in range(4):
        simulate_tick(state)


def show_status(state: GameState) -> None:
    """Display current inventory and cistern storage."""
    inv = state.inventory
    cisterns = [s for s in state.structures.values() if s.kind == "cistern"]
    stored = sum(s.stored for s in cisterns)
    state.messages.append(f"Inv: water {inv['water']/10:.1f}L, scrap {inv['scrap']}, seeds {inv['seeds']}, biomass {inv['biomass']}")
    state.messages.append(f"Cisterns: {stored/10:.1f}L stored across {len(cisterns)} cistern(s)")


def survey_tile(state: GameState) -> None:
    """Display detailed information about current tile."""
    x, y = state.player
    tile = state.tiles[x][y]
    structure = state.structures.get((x, y))
    
    desc = [
        f"Tile {x},{y}",
        f"type={tile.kind}",
        f"elev={tile.elevation:.2f}m",
        f"surf={tile.water.surface_water/10:.1f}L",
    ]
    
    # Show subsurface water summary
    subsurface = tile.water.total_subsurface_water()
    if subsurface > 0:
        desc.append(f"subsrf={subsurface/10:.1f}L")
    
    # Show layer info
    desc.append(f"topsoil={units_to_meters(tile.terrain.topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(tile.terrain.organics_depth):.1f}m")
    
    if tile.well_output > 0:
        desc.append(f"well={tile.well_output/10:.2f}L/t")
    if tile.surface.has_trench:
        desc.append("trench")
    if structure:
        desc.append(f"struct={structure.kind}")
        if structure.kind == "cistern":
            desc.append(f"stored={structure.stored/10:.1f}L")
        elif structure.kind == "planter":
            desc.append(f"growth={structure.growth}%")
    
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """Process a player command. Returns True if should quit."""
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
            state.messages.append("Usage: pour <amount in liters>")
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
        state.messages.append("Commands: w/a/s/d, dig, lower, raise, build <type>, collect, pour <liters>, survey, status, end, quit")
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
    state.messages.append("Units: 1L water = 10 units, 1m soil = 10 units")
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
