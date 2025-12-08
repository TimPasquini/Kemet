"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
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
from structures import (
    Structure,
    STRUCTURE_COSTS,
    build_structure,
    tick_structures,
    TRENCH_EVAP_REDUCTION,
    CISTERN_EVAP_REDUCTION,
)

Point = Tuple[int, int]

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


# Moisture history tracking constants
MOISTURE_HISTORY_MAX = 24  # Track ~2 days of ticks


@dataclass
class Tile:
    """Represents a single map tile with layered terrain and water."""
    kind: str              # Biome type (affects generation, visuals)
    terrain: TerrainColumn
    water: WaterColumn
    surface: SurfaceTraits

    # Tile-level properties
    wellspring_output: int = 0  # Water units produced per tick
    depot: bool = False

    # Moisture tracking for dynamic biome calculation
    moisture_history: List[int] = field(default_factory=list)
    
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
    is_night: bool = False  # True when day timer pauses, simulation continues
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


def update_moisture_history(tile: Tile) -> None:
    """Track rolling moisture average for biome calculation."""
    tile.moisture_history.append(tile.water.total_water())
    if len(tile.moisture_history) > MOISTURE_HISTORY_MAX:
        tile.moisture_history.pop(0)


def get_average_moisture(tile: Tile) -> float:
    """Get average moisture from history, or current if no history."""
    if not tile.moisture_history:
        return float(tile.water.total_water())
    return sum(tile.moisture_history) / len(tile.moisture_history)


def calculate_biome(tile: Tile, neighbor_tiles: List[Tile], elevation_percentile: float) -> str:
    """
    Determine biome type based on tile properties.

    Factors:
    - Elevation percentile (0.0=lowest, 1.0=highest in map)
    - Soil depth and composition
    - Moisture history
    - Neighbor biome influence
    """
    avg_moisture = get_average_moisture(tile)
    soil_depth = tile.terrain.get_total_soil_depth()
    topsoil_material = tile.terrain.topsoil_material

    # Rock: high elevation + thin soil (exposed bedrock/regolith)
    if elevation_percentile > 0.75 and soil_depth < 5:  # <0.5m
        return "rock"

    # Wadi: low elevation + consistently wet
    if elevation_percentile < 0.25 and avg_moisture > 50:  # >5L average
        return "wadi"

    # Dune: sandy topsoil + dry conditions
    if topsoil_material == "sand" and avg_moisture < 20:  # <2L average
        return "dune"

    # Salt: low-mid elevation + very dry + no organic development
    if elevation_percentile < 0.4 and avg_moisture < 15 and tile.terrain.organics_depth == 0:
        return "salt"

    # Neighbor influence for edge smoothing
    if neighbor_tiles:
        neighbor_biomes = [n.kind for n in neighbor_tiles]
        # If surrounded by same biome, tend toward it
        from collections import Counter
        biome_counts = Counter(neighbor_biomes)
        most_common, count = biome_counts.most_common(1)[0]
        # If 3+ neighbors are same biome and we're borderline, adopt it
        if count >= 3 and most_common in ("dune", "flat", "wadi"):
            return most_common

    # Default: flat (generic transitional terrain)
    return "flat"


def calculate_elevation_percentiles(state: "GameState") -> Dict[Point, float]:
    """Calculate elevation percentile for each tile in the map."""
    # Gather all elevations with positions
    elevation_data = []
    for x in range(state.width):
        for y in range(state.height):
            elevation_data.append((state.tiles[x][y].elevation, (x, y)))

    # Sort by elevation
    elevation_data.sort(key=lambda e: e[0])

    # Assign percentiles
    percentiles = {}
    total = len(elevation_data)
    for i, (elev, pos) in enumerate(elevation_data):
        percentiles[pos] = i / max(1, total - 1)

    return percentiles


def recalculate_biomes(state: "GameState") -> None:
    """
    Update all tile biomes based on current properties.

    Called at end of day to allow gradual biome shifts.
    """
    # Calculate elevation percentiles for all tiles
    percentiles = calculate_elevation_percentiles(state)

    changes = 0
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]

            # Skip depot tile (always flat)
            if tile.depot:
                continue

            # Get neighbor tiles
            neighbor_positions = neighbors(x, y, state.width, state.height)
            neighbor_tiles = [state.tiles[nx][ny] for nx, ny in neighbor_positions]

            # Calculate new biome
            elev_pct = percentiles.get((x, y), 0.5)
            new_biome = calculate_biome(tile, neighbor_tiles, elev_pct)

            if new_biome != tile.kind:
                tile.kind = new_biome
                changes += 1

    if changes > 0:
        state.messages.append(f"Landscape shifted: {changes} tiles changed biome.")


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

    # Generate wellsprings with guaranteed lowland primary spring
    _generate_wellsprings(tiles, width, height)

    # Add initial water to wadis
    for x in range(width):
        for y in range(height):
            if tiles[x][y].kind == "wadi":
                tiles[x][y].water.surface_water += random.randint(5, 30)

    return tiles


def _generate_wellsprings(tiles: List[List[Tile]], width: int, height: int) -> None:
    """
    Generate wellsprings with guaranteed lowland primary spring.

    Primary wellspring: placed in lowest 25% elevation, strong flow (0.8-1.2 L/tick)
    Secondary wellsprings: 1-2 additional at varied locations (0.2-0.6 L/tick)
    """
    # Gather all tiles with elevations
    all_tiles = [
        (x, y, tiles[x][y].elevation)
        for x in range(width)
        for y in range(height)
    ]
    all_tiles.sort(key=lambda t: t[2])  # Sort by elevation

    # Lowland candidates: bottom 25%
    lowland_count = max(1, len(all_tiles) // 4)
    lowland_candidates = all_tiles[:lowland_count]

    # Place primary wellspring in lowland (strong flow)
    px, py, _ = random.choice(lowland_candidates)
    tiles[px][py].kind = "wadi"
    tiles[px][py].wellspring_output = random.randint(8, 12)  # 0.8-1.2 L/tick
    tiles[px][py].water.regolith_water = 100
    tiles[px][py].water.surface_water = 80  # Start with 8L (collectible)

    # Place 1-2 secondary wellsprings anywhere (varied output)
    secondary_count = random.randint(1, 2)
    attempts = 0
    placed = 0

    while placed < secondary_count and attempts < 20:
        sx, sy = random.randrange(width), random.randrange(height)
        attempts += 1

        # Don't overwrite primary or depot area (center)
        if tiles[sx][sy].wellspring_output > 0:
            continue
        if (sx, sy) == (width // 2, height // 2):
            continue

        tiles[sx][sy].wellspring_output = random.randint(2, 6)  # 0.2-0.6 L/tick
        tiles[sx][sy].water.regolith_water = 30
        tiles[sx][sy].water.surface_water = 20
        placed += 1


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
    depot_tile.wellspring_output = 0
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


def simulate_tick(state: GameState) -> None:
    """Advance simulation by one tick."""

    # Day/night cycle - only advance timer if not night
    if not state.is_night:
        state.turn_in_day += 1
        daytime = state.turn_in_day % DAY_LENGTH
        day_factor = (1 - abs((daytime / (DAY_LENGTH - 1)) * 2 - 1))
        state.heat = HEAT_MIN + int((HEAT_MAX - HEAT_MIN) * day_factor)

        # Check if day ended
        if state.turn_in_day >= DAY_LENGTH:
            state.is_night = True
            state.heat = HEAT_MIN
            state.messages.append("Night falls. Press Space to rest.")

    # Rain scheduling (continues during night)
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
            state.messages.append("Rain arrives! Wellsprings surge.")

    tick_structures(state, state.heat)

    # Process each tile
    for x in range(state.width):
        for y in range(state.height):
            tile = state.tiles[x][y]
            ttype = TILE_TYPES[tile.kind]

            # Track moisture for biome calculation
            update_moisture_history(tile)

            # Wellsprings feed water into subsurface (regolith layer)
            if tile.wellspring_output > 0:
                gain = tile.wellspring_output
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
    """Rest and advance to next day (only works at night)."""
    if not state.is_night:
        state.messages.append("Can only rest at night. Wait for day to end.")
        return

    state.day += 1
    state.turn_in_day = 0
    state.is_night = False
    state.heat = 100
    state.messages.append(f"Day {state.day} begins.")

    # Recalculate biomes based on accumulated moisture and terrain
    recalculate_biomes(state)


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
    
    if tile.wellspring_output > 0:
        desc.append(f"wellspring={tile.wellspring_output/10:.2f}L/t")
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
