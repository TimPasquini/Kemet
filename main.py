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
    update_moisture_history,
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
    remove_water_proportionally,
    distribute_upward_seepage,
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
    terrain_changed: bool = True              # Flag to trigger elevation grid rebuild

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
    player_state = PlayerState()
    player_state.position = start_subsquare  # Uses setter to center in sub-square

    # Initialize atmosphere layer
    atmosphere = AtmosphereLayer.create(width, height)

    # Initialize global water pool
    from config import INITIAL_WATER_POOL
    water_pool = GlobalWaterPool(total_volume=INITIAL_WATER_POOL)

    return GameState(
        width=width,
        height=height,
        tiles=tiles,
        player_state=player_state,
        atmosphere=atmosphere,
        water_pool=water_pool,
    )


def dig_trench(state: GameState) -> None:
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    if subsquare.has_trench:
        state.messages.append("Already trenched.")
        return
    sub_pos = state.get_action_target_subsquare()
    subsquare.has_trench = True
    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.terrain_changed = True
    # Remove some surface water from this sub-square when digging
    subsquare.surface_water = max(subsquare.surface_water - 10, 0)
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
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    # Get or create terrain override for this sub-square
    terrain = ensure_terrain_override(subsquare, tile.terrain)
    # Find the exposed layer and remove from it
    exposed = terrain.get_exposed_layer()
    if exposed == SoilLayer.BEDROCK:
        state.messages.append("Can't dig further - hit bedrock!")
        return
    if exposed == SoilLayer.REGOLITH:
        state.messages.append("Can't dig further - regolith too hard!")
        return
    if terrain.get_layer_depth(exposed) <= MIN_LAYER_THICKNESS:
        state.messages.append("Layer too thin to dig more.")
        return
    sub_pos = state.get_action_target_subsquare()
    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()  # Terrain changed
    state.terrain_changed = True
    removed = terrain.remove_material_from_layer(exposed, 2)
    material_name = terrain.get_layer_material(exposed)
    new_elev = units_to_meters(terrain.get_surface_elevation()) + subsquare.elevation_offset
    state.messages.append(f"Removed {units_to_meters(removed):.2f}m {material_name}. Elev: {new_elev:.2f}m")


def raise_ground(state: GameState) -> None:
    if state.inventory.scrap < 1:
        state.messages.append("Need 1 scrap to raise ground.")
        return
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sub_pos = state.get_action_target_subsquare()
    # Get or create terrain override for this sub-square
    terrain = ensure_terrain_override(subsquare, tile.terrain)
    state.inventory.scrap -= 1
    subsquare.invalidate_appearance()
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()  # Terrain changed
    state.terrain_changed = True
    # Add to exposed layer (which becomes the new surface)
    exposed = terrain.get_exposed_layer()
    terrain.add_material_to_layer(exposed, 2)
    material_name = terrain.get_layer_material(exposed)
    new_elev = units_to_meters(terrain.get_surface_elevation()) + subsquare.elevation_offset
    state.messages.append(f"Added {material_name} (cost 1 scrap). Elev: {new_elev:.2f}m")


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

    # Get total surface water from sub-squares in this tile
    available = get_tile_surface_water(tile)
    if available <= 5:
        state.messages.append("No water to collect here.")
        return

    # Collect up to 100 units (10L) from this tile
    gathered = remove_water_proportionally(tile, min(100, available))
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

    tx, ty = state.get_action_target_tile()
    tile = state.tiles[tx][ty]

    # Distribute water and update active set
    distribute_upward_seepage(tile, amount_units, state.active_water_subsquares, tx, ty)

    state.inventory.water -= amount_units
    state.messages.append(f"Poured {amount:.1f}L water into soil.")


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
        simulate_surface_seepage(state.tiles, state.width, state.height)
        for x in range(state.width):
            for y in range(state.height):
                update_moisture_history(state.tiles[x][y])

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

        biome_messages = recalculate_biomes(state.tiles, state.width, state.height)
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
    x, y = state.get_action_target_tile()
    sub_pos = state.get_action_target_subsquare()
    structure = state.structures.get(sub_pos)

    surface_water = get_tile_surface_water(tile)

    desc = [f"Tile {x},{y}", f"type={tile.kind}", f"elev={tile.elevation:.2f}m",
            f"surf={surface_water / 10:.1f}L"]
    if tile.water.total_subsurface_water() > 0:
        desc.append(f"subsrf={tile.water.total_subsurface_water() / 10:.1f}L")
    desc.append(f"topsoil={units_to_meters(tile.terrain.topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(tile.terrain.organics_depth):.1f}m")
    if tile.wellspring_output > 0:
        desc.append(f"wellspring={tile.wellspring_output / 10:.2f}L/t")
    if subsquare.has_trench:
        desc.append("trench")
    if structure:
        desc.append(structure.get_survey_string())
    state.messages.append("Survey: " + " | ".join(desc))


def handle_command(state: GameState, cmd: str, args: List[str]) -> bool:
    """Process a player command. Returns True if the game should quit."""
    command_map = {
        "terrain": lambda s, a: terrain_action(s, a[0] if a else ""),
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
