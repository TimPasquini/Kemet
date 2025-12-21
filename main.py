# main.py
"""
Kemet - Desert Farm Prototype
Turn-based simulation: explore, capture water, build, and green a patch.

Uses fixed-layer terrain and integer-based water systems.
"""
from __future__ import annotations

import collections
import random
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Set, Tuple

import numpy as np
from config import SUBGRID_SIZE
from config import (
    MAX_POUR_AMOUNT,
    MIN_LAYER_THICKNESS,
    DEPOT_WATER_AMOUNT,
    DEPOT_SCRAP_AMOUNT,
    DEPOT_SEEDS_AMOUNT,
    STARTING_WATER,
    STARTING_SCRAP,
    STARTING_SEEDS,
    STARTING_BIOMASS,
    MOISTURE_EMA_ALPHA,
)
from ground import (
    SoilLayer,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from subgrid import (
    subgrid_to_tile,
    get_subsquare_index,
    ensure_terrain_override,
    get_subsquare_terrain,
)
from mapgen import (
    Tile,
    TILE_TYPES,
    generate_map,
    recalculate_biomes,
)
from player import PlayerState
from structures import (
    Structure, # Only the base class is needed
    build_structure,
    tick_structures,
)
from simulation.surface import (
    simulate_surface_flow,
    simulate_surface_seepage,
    get_tile_surface_water,
    get_subsquare_elevation,
    remove_water_proportionally,
)
from simulation.subsurface import simulate_subsurface_tick, apply_tile_evaporation
from simulation.erosion import apply_overnight_erosion, accumulate_wind_exposure
from weather import WeatherSystem
from atmosphere import AtmosphereLayer, simulate_atmosphere_tick
from world_state import GlobalWaterPool

Point = Tuple[int, int]


@dataclass
class Inventory:
    """Holds player resources in integer units."""
    water: int = STARTING_WATER
    scrap: int = STARTING_SCRAP
    seeds: int = STARTING_SEEDS
    biomass: int = STARTING_BIOMASS


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
    messages: Deque[str] = field(default_factory=lambda: collections.deque(maxlen=100))

    # Target for actions (set by UI cursor tracking)
    target_subsquare: Point | None = None  # Sub-grid coords
    target_tile: Point | None = None       # Tile coords (derived from target_subsquare)

    # Render cache: set of (sub_x, sub_y) coordinates that need redrawing
    # Using set for O(1) add/check and automatic deduplication
    dirty_subsquares: Set[Point] = field(default_factory=set)

    # Simulation active sets for performance optimization
    active_water_subsquares: Set[Point] = field(default_factory=set)
    active_water_tiles: Set[Point] = field(default_factory=set)
    active_wind_tiles: Set[Point] = field(default_factory=set)

    # Atmosphere layer (regional humidity/wind)
    atmosphere: AtmosphereLayer | None = None

    # Global water pool (conservation of water)
    water_pool: GlobalWaterPool = field(default_factory=GlobalWaterPool)

    # Simulation timing (accumulated time for tick processing)
    _tick_timer: float = 0.0

    # Structure lookup cache: tiles that contain cisterns (for evaporation optimization)
    _tiles_with_cisterns: set = field(default_factory=set)

    # Elevation range cache (invalidated on terrain changes)
    _cached_elevation_range: Tuple[float, float] | None = None

    # === Vectorized Simulation State ===
    water_grid: np.ndarray | None = None      # Shape: (width*3, height*3), dtype=int32
    elevation_grid: np.ndarray | None = None  # Shape: (width*3, height*3), dtype=int32
    moisture_grid: np.ndarray | None = None   # Shape: (width, height), dtype=float64 (EMA)
    trench_grid: np.ndarray | None = None     # Shape: (width*3, height*3), dtype=uint8
    terrain_changed: bool = True              # Flag to trigger elevation grid rebuild

    # === Unified Terrain State (The Source of Truth) ===
    # Shape: (6, width*3, height*3), dtype=int32. Index using SoilLayer enum.
    terrain_layers: np.ndarray | None = None
    # Shape: (width*3, height*3), dtype=int32. Base elevation of bedrock.
    bedrock_base: np.ndarray | None = None
    # Shape: (width*3, height*3), dtype=int32. Micro-terrain offset in depth units.
    elevation_offset_grid: np.ndarray | None = None

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

    def set_target(self, subsquare: Point | None) -> None:
        """Set the target for actions from UI cursor tracking."""
        self.target_subsquare = subsquare
        if subsquare is not None:
            self.target_tile = subgrid_to_tile(subsquare[0], subsquare[1])
        else:
            self.target_tile = None

    def get_action_target_tile(self) -> Point:
        """Get the tile to target for actions (cursor target or player position)."""
        return self.target_tile if self.target_tile is not None else self.player

    def get_action_target_subsquare(self) -> Point:
        """Get the sub-square to target for actions (cursor target or player position)."""
        return self.target_subsquare if self.target_subsquare is not None else self.player_subsquare

    def get_target_tile_and_subsquare(self) -> tuple[Tile, "SubSquare", Point]:
        """Get the tile, sub-square, and local index for the current action target.

        Returns:
            (tile, subsquare, (local_x, local_y)) for the targeted sub-square
        """
        from subgrid import SubSquare  # Import here to avoid circular imports
        sub_pos = self.get_action_target_subsquare()
        tile_pos = subgrid_to_tile(sub_pos[0], sub_pos[1])
        local_x, local_y = get_subsquare_index(sub_pos[0], sub_pos[1])
        tile = self.tiles[tile_pos[0]][tile_pos[1]]
        subsquare = tile.subgrid[local_x][local_y]
        return tile, subsquare, (local_x, local_y)

    def is_subsquare_blocked(self, sub_x: int, sub_y: int) -> bool:
        """Check if a subsquare is blocked for movement."""
        # Bounds check
        if not (0 <= sub_x < self.width * 3 and 0 <= sub_y < self.height * 3):
            return True

        # Check for structure (O(1) lookup)
        if (sub_x, sub_y) in self.structures:
            return True

        # Future: Check for impassable terrain types in your new unified grid
        
        return False

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

    # === Structure Cache Methods ===
    def tile_has_cistern(self, tile_x: int, tile_y: int) -> bool:
        """Check if a tile has a cistern (O(1) lookup)."""
        return (tile_x, tile_y) in self._tiles_with_cisterns

    def register_cistern(self, tile_x: int, tile_y: int) -> None:
        """Register that a tile now has a cistern. Called when cistern is built."""
        self._tiles_with_cisterns.add((tile_x, tile_y))

    # === Elevation Range Cache ===
    def get_elevation_range(self) -> Tuple[float, float]:
        """Get cached elevation range, calculating if needed.

        Returns (min_elevation, max_elevation) across all tiles.
        """
        if self._cached_elevation_range is None:
            elevations = [
                self.tiles[x][y].elevation
                for x in range(self.width)
                for y in range(self.height)
            ]
            self._cached_elevation_range = (min(elevations), max(elevations)) if elevations else (0.0, 0.0)
        return self._cached_elevation_range

    def invalidate_elevation_range(self) -> None:
        """Mark elevation range cache as stale. Call when terrain is modified."""
        self._cached_elevation_range = None


def build_initial_state(width: int = 10, height: int = 10) -> GameState:
    """Create a new game state with generated map."""
    from subgrid import tile_center_subsquare
    
    # Initialize water grid early for map generation
    water_grid = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.int32)
    
    # Initialize unified terrain arrays
    terrain_layers = np.zeros((len(SoilLayer), width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.int32)
    bedrock_base = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.int32)
    elevation_offset_grid = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.int32)
    
    elevation_grid = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.int32)

    tiles = generate_map(width, height, water_grid)
    start_tile = (width // 2, height // 2)

    # Set up depot at player start location
    depot_tile = tiles[start_tile[0]][start_tile[1]]
    depot_tile.kind = "flat"
    depot_tile.surface.has_trench = False
    depot_tile.terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    depot_tile.wellspring_output = 0
    depot_tile.depot = True

    # Populate unified terrain arrays from the generated object graph
    for x in range(width):
        for y in range(height):
            tile = tiles[x][y]
            for sx in range(SUBGRID_SIZE):
                for sy in range(SUBGRID_SIZE):
                    # Calculate global sub-grid coordinates
                    gx, gy = x * SUBGRID_SIZE + sx, y * SUBGRID_SIZE + sy
                    
                    subsquare = tile.subgrid[sx][sy]
                    # Use override if present, else tile terrain
                    terrain = get_subsquare_terrain(subsquare, tile.terrain)
                    
                    # Fill bedrock base
                    bedrock_base[gx, gy] = terrain.bedrock_base
                    # Fill elevation offset (convert meters to units)
                    elevation_offset_grid[gx, gy] = elevation_to_units(subsquare.elevation_offset)
                    # Fill layers
                    for layer in SoilLayer:
                        terrain_layers[layer, gx, gy] = terrain.get_layer_depth(layer)

    # Initialize player at center of starting tile (in sub-grid coords)
    start_subsquare = tile_center_subsquare(start_tile[0], start_tile[1])
    player_state = PlayerState()
    player_state.position = start_subsquare  # Uses setter to center in sub-square

    # Initialize atmosphere layer
    atmosphere = AtmosphereLayer.create(width, height)

    # Initialize global water pool
    from config import INITIAL_WATER_POOL
    water_pool = GlobalWaterPool(total_volume=INITIAL_WATER_POOL)

    # Initialize moisture grid
    moisture_grid = np.zeros((width, height), dtype=float)

    # Initialize trench grid
    trench_grid = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.uint8)

    return GameState(
        width=width,
        height=height,
        tiles=tiles,
        player_state=player_state,
        water_grid=water_grid,
        elevation_grid=elevation_grid,
        atmosphere=atmosphere,
        water_pool=water_pool,
        moisture_grid=moisture_grid,
        trench_grid=trench_grid,
        terrain_layers=terrain_layers,
        bedrock_base=bedrock_base,
        elevation_offset_grid=elevation_offset_grid,
    )


def dig_trench(state: GameState) -> None:
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sub_pos = state.get_action_target_subsquare()
    if state.trench_grid[sub_pos]:
        state.messages.append("Already trenched.")
        return
    state.trench_grid[sub_pos] = 1
    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.terrain_changed = True
    # Remove some surface water from this sub-square's grid cell when digging
    state.water_grid[sub_pos] = max(state.water_grid[sub_pos] - 10, 0)
    state.messages.append("Dug a trench; flow improves, evap drops here.")


def terrain_action(state: GameState, action: str, args: List[str]) -> None:
    """Dispatch terrain tool actions (shovel submenu)."""
    if action == "trench":
        dig_trench(state)
    elif action == "lower":
        # args[0] should be the limit layer name (e.g. "topsoil")
        limit = args[0] if args else "bedrock"
        lower_ground(state, limit)
    elif action == "raise":
        # args[0] should be the target layer name (e.g. "topsoil")
        target = args[0] if args else "topsoil"
        raise_ground(state, target)
    else:
        state.messages.append(f"Unknown terrain action: {action}")


def lower_ground(state: GameState, min_layer_name: str = "bedrock") -> None:
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    # Get or create terrain override for this sub-square
    terrain = ensure_terrain_override(subsquare, tile.terrain)
    # Find the exposed layer and remove from it
    exposed = terrain.get_exposed_layer()

    sub_pos = state.get_action_target_subsquare()
    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()  # Terrain changed
    state.terrain_changed = True
    removed = terrain.remove_material_from_layer(exposed, 2)
    material_name = terrain.get_layer_material(exposed)
    new_elev = units_to_meters(terrain.get_surface_elevation()) + subsquare.elevation_offset
    state.messages.append(f"Removed {units_to_meters(removed):.2f}m {material_name}. Elev: {new_elev:.2f}m")


def raise_ground(state: GameState, target_layer_name: str = "topsoil") -> None:
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sub_pos = state.get_action_target_subsquare()
    # Get or create terrain override for this sub-square
    terrain = ensure_terrain_override(subsquare, tile.terrain)

    cost = 0
    if state.inventory.scrap > 0:
        state.inventory.scrap -= 1
        cost = 1

    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()  # Terrain changed
    state.terrain_changed = True
    
    # Resolve target string to enum
    try:
        target_layer = SoilLayer[target_layer_name.upper()]
    except KeyError:
        target_layer = SoilLayer.TOPSOIL

    terrain.add_material_to_layer(target_layer, 2)
    material_name = terrain.get_layer_material(target_layer)
    new_elev = units_to_meters(terrain.get_surface_elevation()) + subsquare.elevation_offset
    state.messages.append(f"Added {material_name} (cost {cost} scrap). Elev: {new_elev:.2f}m")


def collect_water(state: GameState) -> None:
    tx, ty = state.get_action_target_tile()
    tile = state.tiles[tx][ty]
    if tile.depot:
        state.inventory.water += DEPOT_WATER_AMOUNT
        state.inventory.scrap += DEPOT_SCRAP_AMOUNT
        state.inventory.seeds += DEPOT_SEEDS_AMOUNT
        state.messages.append(
            f"Depot resupply: +{DEPOT_WATER_AMOUNT / 10:.1f}L water, +{DEPOT_SCRAP_AMOUNT} scrap, +{DEPOT_SEEDS_AMOUNT} seeds.")
        return

    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sx, sy = state.get_action_target_subsquare()
    available = state.water_grid[sx, sy]

    if available <= 0:
        state.messages.append("No water to collect here.")
        return

    gathered = min(100, available)
    state.water_grid[sx, sy] -= gathered
    subsquare.check_water_threshold(state.water_grid[sx, sy])
    state.active_water_subsquares.add(state.get_action_target_subsquare())
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

    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sx, sy = state.get_action_target_subsquare()
    state.water_grid[sx, sy] += amount_units
    subsquare.check_water_threshold(state.water_grid[sx, sy])
    
    # Add to active set for flow simulation
    state.active_water_subsquares.add(state.get_action_target_subsquare())

    state.inventory.water -= amount_units
    state.messages.append(f"Poured {amount:.1f}L water.")


def simulate_tick(state: GameState) -> None:
    """Run one simulation tick using active sets for performance."""
    weather_messages = state.weather.tick()
    state.messages.extend(weather_messages)
    tick_structures(state, state.heat)

    tick = state.weather.turn_in_day

    if tick % 2 == 0:
        simulate_surface_flow(state)

    if tick % 2 == 1:
        # Seepage still iterates all tiles, but is less frequent.
        # Could be optimized further by tracking active surface water tiles.
        simulate_surface_seepage(state)
        
        # Update moisture history using Vectorized/EMA approach
        # Calculate current total water (surface + subsurface)
        # Note: We iterate to bridge the object gap until subsurface is fully vectorized
        current_moisture = np.zeros((state.width, state.height), dtype=float)
        for x in range(state.width):
            for y in range(state.height):
                tile = state.tiles[x][y]
                # Surface water sum
                surf = get_tile_surface_water(tile, state.water_grid, x, y)
                # Subsurface water sum
                sub = tile.water.total_subsurface_water()
                current_moisture[x, y] = surf + sub

        if state.moisture_grid is None:
            state.moisture_grid = current_moisture
        else:
            # Apply Exponential Moving Average
            state.moisture_grid = (1 - MOISTURE_EMA_ALPHA) * state.moisture_grid + MOISTURE_EMA_ALPHA * current_moisture

    if tick % 4 == 1:
        simulate_subsurface_tick(state)

    apply_tile_evaporation(state)

    if state.atmosphere is not None:
        simulate_atmosphere_tick(state.atmosphere, state.heat)
        if state.weather.turn_in_day % 10 == 0:
            accumulate_wind_exposure(state)


def end_day(state: GameState) -> None:
    messages = state.weather.end_day()
    state.messages.extend(messages)
    if messages and "begins" in messages[-1]:
        erosion_messages = apply_overnight_erosion(state)
        state.messages.extend(erosion_messages)

        biome_messages = recalculate_biomes(state.tiles, state.width, state.height, state.moisture_grid)
        state.messages.extend(biome_messages)

        for row in state.tiles:
            for tile in row:
                for sub_row in tile.subgrid:
                    for subsquare in sub_row:
                        subsquare.invalidate_appearance()


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

def survey_tile(state: GameState) -> None:
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    lx, ly = state.get_action_target_subsquare()
    x, y = state.get_action_target_tile()
    sub_pos = state.get_action_target_subsquare()
    structure = state.structures.get(sub_pos)
    surface_water = state.water_grid[sub_pos]

    elev_m = units_to_meters(get_subsquare_elevation(tile, sub_pos[0] % 3, sub_pos[1] % 3))

    desc = [f"Tile {x},{y}", f"Sub {sub_pos[0]%3},{sub_pos[1]%3}", f"elev={elev_m:.2f}m",
            f"surf={surface_water / 10:.1f}L"]
    if tile.water.total_subsurface_water() > 0:
        desc.append(f"subsrf={tile.water.total_subsurface_water() / 10:.1f}L")
    desc.append(f"topsoil={units_to_meters(tile.terrain.topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(tile.terrain.organics_depth):.1f}m")
    if tile.wellspring_output > 0:
        desc.append(f"wellspring={tile.wellspring_output / 10:.2f}L/t")
    if state.trench_grid[sub_pos]:
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
