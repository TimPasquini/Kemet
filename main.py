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
from config import SUBGRID_SIZE, GRID_WIDTH, GRID_HEIGHT
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
    MIN_BEDROCK_ELEVATION,
)
from ground import (
    SoilLayer,
    MATERIAL_LIBRARY,
    TerrainColumn,
    SurfaceTraits,
    create_default_terrain,
    elevation_to_units,
    units_to_meters,
)
from subgrid import (
    SubSquare,
    subgrid_to_tile,
    get_subsquare_index,
    get_subsquare_terrain,
)
from mapgen import (
    Tile,
    TILE_TYPES,
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
    remove_water_proportionally,
)
from simulation.subsurface import apply_tile_evaporation
from simulation.subsurface_vectorized import simulate_subsurface_tick_vectorized
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
    water_grid: np.ndarray | None = None      # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32
    elevation_grid: np.ndarray | None = None  # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32
    moisture_grid: np.ndarray | None = None   # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float64 (EMA)
    trench_grid: np.ndarray | None = None     # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=uint8

    # Daily accumulator grids for erosion
    water_passage_grid: np.ndarray | None = None  # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float
    wind_exposure_grid: np.ndarray | None = None  # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float

    terrain_changed: bool = True              # Flag to trigger elevation grid rebuild

    # === Unified Terrain State (The Source of Truth) ===
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype=int32. Index using SoilLayer enum.
    terrain_layers: np.ndarray | None = None
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype=int32. Subsurface water.
    subsurface_water_grid: np.ndarray | None = None
    # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32. Base elevation of bedrock.
    bedrock_base: np.ndarray | None = None

    # === Material Property Grids (for physics calculations) ===
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype='U20'. Material name for each layer.
    terrain_materials: np.ndarray | None = None
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype=int32. Vertical permeability (0-100).
    permeability_vert_grid: np.ndarray | None = None
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype=int32. Horizontal permeability (0-100).
    permeability_horiz_grid: np.ndarray | None = None
    # Shape: (6, GRID_WIDTH, GRID_HEIGHT), dtype=int32. Porosity (0-100).
    porosity_grid: np.ndarray | None = None

    # === Wellspring Grid ===
    # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32. Water output rate per grid cell.
    wellspring_grid: np.ndarray | None = None

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
    """Create a new game state with generated map (grid-first approach)."""
    from subgrid import tile_center_subsquare
    from mapgen import generate_grids_direct

    # Generate all grid data directly (array-first approach)
    grid_width = width * SUBGRID_SIZE
    grid_height = height * SUBGRID_SIZE
    grids = generate_grids_direct(grid_width, grid_height)

    # Extract grids from returned dict
    terrain_layers = grids["terrain_layers"]
    terrain_materials = grids["terrain_materials"]
    subsurface_water_grid = grids["subsurface_water_grid"]
    bedrock_base = grids["bedrock_base"]
    wellspring_grid = grids["wellspring_grid"]
    water_grid = grids["water_grid"]
    kind_grid = grids["kind_grid"]

    # Calculate material property grids from terrain_materials
    permeability_vert_grid = np.zeros((len(SoilLayer), grid_width, grid_height), dtype=np.int32)
    permeability_horiz_grid = np.zeros((len(SoilLayer), grid_width, grid_height), dtype=np.int32)
    porosity_grid = np.zeros((len(SoilLayer), grid_width, grid_height), dtype=np.int32)

    for layer in SoilLayer:
        for gx in range(grid_width):
            for gy in range(grid_height):
                material_name = terrain_materials[layer, gx, gy]
                material_props = MATERIAL_LIBRARY.get(material_name)
                if material_props:
                    permeability_vert_grid[layer, gx, gy] = material_props.permeability_vertical
                    permeability_horiz_grid[layer, gx, gy] = material_props.permeability_horizontal
                    porosity_grid[layer, gx, gy] = material_props.porosity

    # Create minimal stub tile objects for backwards compatibility
    # Note: Real terrain data is in grids. Tiles are legacy and will be removed.
    tiles: List[List[Tile]] = []
    for x in range(width):
        column = []
        for y in range(height):
            # Get representative values from center cell of the 3x3 tile region
            center_gx = x * SUBGRID_SIZE + 1
            center_gy = y * SUBGRID_SIZE + 1

            # Create stub terrain (just for compatibility, not accurate)
            stub_terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))

            # Note: WaterColumn no longer needed - all water data in grids

            # Create subgrid with elevation offsets from grid
            subgrid = []
            for sx in range(SUBGRID_SIZE):
                row = []
                for sy in range(SUBGRID_SIZE):
                    row.append(SubSquare())
                subgrid.append(row)

            # Get biome kind from grid
            kind = str(kind_grid[center_gx, center_gy])

            # Check wellspring from center cell
            wellspring_output = wellspring_grid[center_gx, center_gy]

            # Create minimal stub tile
            tile = Tile(
                kind=kind,
                terrain=stub_terrain,  # Stub only - real data in grids
                water=None,  # No longer used - real data in subsurface_water_grid
                surface=SurfaceTraits(),
                wellspring_output=wellspring_output,
                subgrid=subgrid,
            )
            column.append(tile)
        tiles.append(column)

    start_tile = (width // 2, height // 2)

    # Set up depot at player start location (in grids)
    depot_tile = tiles[start_tile[0]][start_tile[1]]
    depot_tile.kind = "flat"

    # Update grids for depot location - create good starting terrain
    depot_terrain = create_default_terrain(elevation_to_units(-2.0), elevation_to_units(1.0))
    for sx in range(SUBGRID_SIZE):
        for sy in range(SUBGRID_SIZE):
            gx = start_tile[0] * SUBGRID_SIZE + sx
            gy = start_tile[1] * SUBGRID_SIZE + sy
            kind_grid[gx, gy] = "flat"
            wellspring_grid[gx, gy] = 0
            bedrock_base[gx, gy] = depot_terrain.bedrock_base
            for layer in SoilLayer:
                terrain_layers[layer, gx, gy] = depot_terrain.get_layer_depth(layer)
                terrain_materials[layer, gx, gy] = depot_terrain.get_layer_material(layer)

    # Initialize player at center of starting tile (in sub-grid coords)
    start_subsquare = tile_center_subsquare(start_tile[0], start_tile[1])
    player_state = PlayerState()
    player_state.position = start_subsquare  # Uses setter to center in sub-square

    # Initialize atmosphere layer
    atmosphere = AtmosphereLayer.create(width, height)

    # Initialize global water pool
    from config import INITIAL_WATER_POOL
    water_pool = GlobalWaterPool(total_volume=INITIAL_WATER_POOL)

    # Initialize moisture grid at grid resolution
    moisture_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)

    # Initialize trench grid
    trench_grid = np.zeros((width * SUBGRID_SIZE, height * SUBGRID_SIZE), dtype=np.uint8)

    # Initialize daily accumulator grids for erosion
    water_passage_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)
    wind_exposure_grid = np.zeros((GRID_WIDTH, GRID_HEIGHT), dtype=float)

    # Initialize elevation_grid (calculated from other grids)
    elevation_grid = bedrock_base + np.sum(terrain_layers, axis=0)

    # Create game state
    state = GameState(
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
        water_passage_grid=water_passage_grid,
        wind_exposure_grid=wind_exposure_grid,
        terrain_layers=terrain_layers,
        subsurface_water_grid=subsurface_water_grid,
        bedrock_base=bedrock_base,
        terrain_materials=terrain_materials,
        permeability_vert_grid=permeability_vert_grid,
        permeability_horiz_grid=permeability_horiz_grid,
        porosity_grid=porosity_grid,
        wellspring_grid=wellspring_grid,
    )

    # Create depot structure at starting subsquare
    from structures import Depot
    from subgrid import get_subsquare_index
    state.structures[start_subsquare] = Depot()
    local_x, local_y = get_subsquare_index(start_subsquare[0], start_subsquare[1])
    depot_tile.subgrid[local_x][local_y].structure_id = 1

    return state


def _get_perpendicular_neighbors(px: int, py: int, tx: int, ty: int, grid_width: int, grid_height: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Get left and right perpendicular neighbors relative to player-target direction.

    Args:
        px, py: Player position (grid coords)
        tx, ty: Target position (grid coords)
        grid_width, grid_height: Grid bounds

    Returns:
        (left_neighbor, right_neighbor) tuples or None if out of bounds
    """
    # Direction vector from player to target
    dx = tx - px
    dy = ty - py

    # Perpendicular vectors (rotate 90°)
    # Left (CCW): (dx, dy) → (-dy, dx)
    # Right (CW): (dx, dy) → (dy, -dx)
    left_dx, left_dy = -dy, dx
    right_dx, right_dy = dy, -dx

    # Normalize to unit length (or closest grid cell)
    import math
    left_len = math.sqrt(left_dx**2 + left_dy**2)
    right_len = math.sqrt(right_dx**2 + right_dy**2)

    if left_len > 0:
        left_dx = round(left_dx / left_len)
        left_dy = round(left_dy / left_len)
    if right_len > 0:
        right_dx = round(right_dx / right_len)
        right_dy = round(right_dy / right_len)

    # Calculate neighbor positions
    left_pos = (tx + left_dx, ty + left_dy)
    right_pos = (tx + right_dx, ty + right_dy)

    # Check bounds
    left_valid = 0 <= left_pos[0] < grid_width and 0 <= left_pos[1] < grid_height
    right_valid = 0 <= right_pos[0] < grid_width and 0 <= right_pos[1] < grid_height

    return (left_pos if left_valid else None, right_pos if right_valid else None)


def dig_trench(state: GameState, mode: str) -> None:
    """Dig a trench with the specified mode: 'flat', 'slope_down', or 'slope_up'.

    Common setup handles position calculation and validation.
    Mode-specific logic handles material removal and redistribution.

    Args:
        state: Game state
        mode: One of 'flat', 'slope_down', 'slope_up'
    """
    from config import GRID_WIDTH, GRID_HEIGHT, TRENCH_SLOPE_DROP
    import math

    # ========== COMMON SETUP ==========
    sub_pos = state.get_action_target_subsquare()
    sx, sy = sub_pos
    px, py = state.player_subsquare

    # Get perpendicular neighbors (for berms)
    left_pos, right_pos = _get_perpendicular_neighbors(px, py, sx, sy, GRID_WIDTH, GRID_HEIGHT)

    # Get axial direction
    dx, dy = sx - px, sy - py
    length = math.sqrt(dx**2 + dy**2)
    if length > 0:
        dx_norm, dy_norm = round(dx / length), round(dy / length)
    else:
        state.messages.append("Cannot trench at player position.")
        return

    # Calculate origin (backward) and exit (forward) positions
    backward_pos = (sx - dx_norm, sy - dy_norm)
    forward_pos = (sx + dx_norm, sy + dy_norm)

    # Validate positions
    if not (0 <= backward_pos[0] < GRID_WIDTH and 0 <= backward_pos[1] < GRID_HEIGHT):
        state.messages.append("Cannot trench - invalid origin position.")
        return
    if mode in ["slope_down", "slope_up"]:
        if not (0 <= forward_pos[0] < GRID_WIDTH and 0 <= forward_pos[1] < GRID_HEIGHT):
            state.messages.append("Cannot trench - invalid exit position.")
            return

    # Get current elevations
    origin_elev = state.elevation_grid[backward_pos]
    target_elev = state.elevation_grid[sx, sy]
    exit_elev = state.elevation_grid[forward_pos] if mode in ["slope_down", "slope_up"] else None

    # ========== MODE-SPECIFIC LOGIC ==========
    match mode:
        case "flat":
            _dig_trench_flat_impl(state, sx, sy, origin_elev, target_elev,
                                 backward_pos, forward_pos, left_pos, right_pos)
        case "slope_down":
            _dig_trench_slope_down_impl(state, sx, sy, origin_elev, target_elev, exit_elev,
                                       backward_pos, forward_pos, left_pos, right_pos)
        case "slope_up":
            _dig_trench_slope_up_impl(state, sx, sy, origin_elev, target_elev, exit_elev,
                                     backward_pos, forward_pos, left_pos, right_pos)
        case _:
            state.messages.append(f"Unknown trench mode: {mode}")


def _dig_trench_flat_impl(state: GameState, sx: int, sy: int,
                          origin_elev: int, target_elev: int,
                          backward_pos: tuple, forward_pos: tuple,
                          left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of flat trenching mode."""
    from config import GRID_WIDTH, GRID_HEIGHT

    # Find exposed layer at target (top to bottom)
    exposed_layer = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed_layer = layer
            break

    if exposed_layer is None:
        state.messages.append("Cannot trench bedrock.")
        return

    # Calculate how much to modify target
    elevation_diff = target_elev - origin_elev

    if elevation_diff <= 0:
        # Target is already at or below origin - no trenching needed
        state.messages.append(f"Target already at channel level (origin: {units_to_meters(origin_elev):.2f}m).")
        return

    # AUTO-COMPLETE: Remove ALL material needed to reach origin level (not just TRENCH_DEPTH)
    material_to_remove = min(elevation_diff, state.terrain_layers[exposed_layer, sx, sy])

    if material_to_remove == 0:
        state.messages.append("No material to remove.")
        return

    # Remove from target
    state.terrain_layers[exposed_layer, sx, sy] -= material_to_remove
    if state.terrain_layers[exposed_layer, sx, sy] == 0:
        state.terrain_materials[exposed_layer, sx, sy] = ""

    # Distribute material with priority: exit → lower side → even split
    material_pool = material_to_remove

    # PRIORITY 1: Fill forward (exit) to origin level
    if (0 <= forward_pos[0] < GRID_WIDTH and 0 <= forward_pos[1] < GRID_HEIGHT):
        forward_elev = state.elevation_grid[forward_pos]
        if forward_elev < origin_elev and material_pool > 0:
            forward_deficit = origin_elev - forward_elev
            fill_amount = min(material_pool, forward_deficit)
            layer = _get_or_create_layer(state, forward_pos[0], forward_pos[1])
            state.terrain_layers[layer, forward_pos[0], forward_pos[1]] += fill_amount
            state.dirty_subsquares.add(forward_pos)
            material_pool -= fill_amount

    # PRIORITY 2: Fill lower side to match higher side
    if material_pool > 0 and left_pos and right_pos:
        left_elev = state.elevation_grid[left_pos]
        right_elev = state.elevation_grid[right_pos]

        if left_elev < right_elev:
            # Fill left to match right
            deficit = right_elev - left_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            state.terrain_layers[layer, left_pos[0], left_pos[1]] += fill_amount
            state.dirty_subsquares.add(left_pos)
            material_pool -= fill_amount
        elif right_elev < left_elev:
            # Fill right to match left
            deficit = left_elev - right_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[layer, right_pos[0], right_pos[1]] += fill_amount
            state.dirty_subsquares.add(right_pos)
            material_pool -= fill_amount

    # PRIORITY 3: Distribute remaining evenly to sides
    if material_pool > 0:
        recipients = []
        if left_pos:
            recipients.append(left_pos)
        if right_pos:
            recipients.append(right_pos)

        if recipients:
            per_recipient = material_pool // len(recipients)
            remainder = material_pool % len(recipients)

            for i, recipient in enumerate(recipients):
                layer = _get_or_create_layer(state, recipient[0], recipient[1])
                amount = per_recipient + (1 if i < remainder else 0)
                state.terrain_layers[layer, recipient[0], recipient[1]] += amount
                state.dirty_subsquares.add(recipient)

    # Mark changes
    state.dirty_subsquares.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()

    tile_x, tile_y = sx // 3, sy // 3
    local_x, local_y = sx % 3, sy % 3

    state.messages.append(f"Trenched (flat): leveled to origin height, moved {units_to_meters(material_to_remove):.1f}m.")


def _find_exposed_layer(state: GameState, sx: int, sy: int) -> SoilLayer | None:
    """Find the exposed (topmost) layer at a cell, or None if bedrock."""
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            return layer
    return None


def _get_or_create_layer(state: GameState, sx: int, sy: int) -> SoilLayer:
    """Get the exposed (topmost) layer at a cell, or topsoil if bedrock exposed."""
    layer = _find_exposed_layer(state, sx, sy)
    return layer if layer is not None else SoilLayer.TOPSOIL


def _dig_trench_slope_down_impl(state: GameState, sx: int, sy: int,
                                origin_elev: int, target_elev: int, exit_elev: int,
                                backward_pos: tuple, forward_pos: tuple,
                                left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of slope down trenching mode."""
    from config import TRENCH_SLOPE_DROP

    material_pool = 0

    # Goal: origin > selection > exit with TRENCH_SLOPE_DROP between each
    # Strategy: Pull from higher squares to raise lower ones

    # Check if exit is too high (higher than selection)
    if exit_elev > target_elev:
        # Pull from exit to raise selection
        exit_layer = _find_exposed_layer(state, forward_pos[0], forward_pos[1])
        if exit_layer is not None:
            material_from_exit = state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]]
            needed_for_selection = max(0, exit_elev - TRENCH_SLOPE_DROP - target_elev)
            to_remove_exit = min(material_from_exit, needed_for_selection)

            if to_remove_exit > 0:
                state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]] -= to_remove_exit
                if state.terrain_layers[exit_layer, forward_pos[0], forward_pos[1]] == 0:
                    state.terrain_materials[exit_layer, forward_pos[0], forward_pos[1]] = ""

                # Add to selection
                layer = _get_or_create_layer(state, sx, sy)
                state.terrain_layers[layer, sx, sy] += to_remove_exit
                state.dirty_subsquares.add(forward_pos)
                state.dirty_subsquares.add((sx, sy))

                # Update elevation for next check
                target_elev += to_remove_exit

    # Check if selection is too high relative to origin
    if target_elev > origin_elev:
        # Pull from selection to raise origin (halfway)
        exposed_layer = _find_exposed_layer(state, sx, sy)
        if exposed_layer is None:
            state.messages.append("Cannot trench bedrock.")
            return

        material_from_selection = state.terrain_layers[exposed_layer, sx, sy]
        if material_from_selection > 0:
            # Calculate halfway point
            max_fill_origin = target_elev - ((target_elev - origin_elev) // 2)
            deficit_origin = max(0, max_fill_origin - origin_elev)
            to_origin = min(material_from_selection, deficit_origin)

            if to_origin > 0:
                state.terrain_layers[exposed_layer, sx, sy] -= to_origin
                if state.terrain_layers[exposed_layer, sx, sy] == 0:
                    state.terrain_materials[exposed_layer, sx, sy] = ""

                # Fill origin
                layer = _get_or_create_layer(state, backward_pos[0], backward_pos[1])
                state.terrain_layers[layer, backward_pos[0], backward_pos[1]] += to_origin
                state.dirty_subsquares.add(backward_pos)
                state.dirty_subsquares.add((sx, sy))

            # Any remaining from selection goes to material pool for sides
            remaining = state.terrain_layers[exposed_layer, sx, sy]
            if remaining > 0:
                material_pool += remaining
                state.terrain_layers[exposed_layer, sx, sy] = 0
                state.terrain_materials[exposed_layer, sx, sy] = ""

    # Distribute any excess to sides
    if material_pool > 0:
        _distribute_to_sides(state, material_pool, left_pos, right_pos)

    # Mark changes
    state.dirty_subsquares.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()
    _invalidate_tile_appearance(state, sx, sy)

    state.messages.append(f"Slope (Down): gradient origin>sel>exit created.")


def _dig_trench_slope_up_impl(state: GameState, sx: int, sy: int,
                              origin_elev: int, target_elev: int, exit_elev: int,
                              backward_pos: tuple, forward_pos: tuple,
                              left_pos: tuple, right_pos: tuple) -> None:
    """Implementation of slope up trenching mode."""
    from config import TRENCH_SLOPE_DROP

    # Remove LIMITED material from selection (keep it above origin + margin)
    exposed_layer = _find_exposed_layer(state, sx, sy)
    if exposed_layer is None:
        state.messages.append("Cannot trench bedrock.")
        return

    available = state.terrain_layers[exposed_layer, sx, sy]
    if available == 0:
        state.messages.append("No material to remove.")
        return

    # Only remove enough to keep selection at least TRENCH_SLOPE_DROP above origin
    min_target_elev = origin_elev + TRENCH_SLOPE_DROP
    max_removal = max(0, target_elev - min_target_elev)
    material_from_target = min(available, max_removal)

    if material_from_target == 0:
        state.messages.append("Selection already at minimum for upslope.")
        return

    state.terrain_layers[exposed_layer, sx, sy] -= material_from_target
    if state.terrain_layers[exposed_layer, sx, sy] == 0:
        state.terrain_materials[exposed_layer, sx, sy] = ""

    material_pool = material_from_target

    # Raise exit above selection, then distribute remainder to sides
    exit_elev = state.elevation_grid[forward_pos]
    target_elev_after = target_elev - material_from_target  # Selection after removal

    # Calculate how much needed to raise exit above selection
    needed_for_exit = max(0, target_elev_after + TRENCH_SLOPE_DROP - exit_elev)
    to_exit = min(material_pool, needed_for_exit)

    if to_exit > 0:
        layer = _get_or_create_layer(state, forward_pos[0], forward_pos[1])
        state.terrain_layers[layer, forward_pos[0], forward_pos[1]] += to_exit
        state.dirty_subsquares.add(forward_pos)
        material_pool -= to_exit

    # Distribute remainder to sides
    if material_pool > 0:
        _distribute_to_sides(state, material_pool, left_pos, right_pos)

    # Mark changes
    state.dirty_subsquares.add((sx, sy))
    state.terrain_changed = True
    state.invalidate_elevation_range()
    _invalidate_tile_appearance(state, sx, sy)

    state.messages.append(f"Slope (Up): gradient origin<sel<exit, moved {units_to_meters(material_from_target):.1f}m.")


def _distribute_to_sides(state: GameState, material_pool: int, left_pos, right_pos) -> None:
    """Helper to distribute material to perpendicular sides with elevation-awareness."""
    if material_pool <= 0:
        return

    if left_pos and right_pos:
        left_elev = state.elevation_grid[left_pos]
        right_elev = state.elevation_grid[right_pos]

        # Fill lower side first
        if left_elev < right_elev:
            deficit = right_elev - left_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            state.terrain_layers[layer, left_pos[0], left_pos[1]] += fill_amount
            state.dirty_subsquares.add(left_pos)
            material_pool -= fill_amount
        elif right_elev < left_elev:
            deficit = left_elev - right_elev
            fill_amount = min(material_pool, deficit)
            layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[layer, right_pos[0], right_pos[1]] += fill_amount
            state.dirty_subsquares.add(right_pos)
            material_pool -= fill_amount

        # Distribute remaining evenly
        if material_pool > 0:
            half = material_pool // 2
            left_layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
            right_layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
            state.terrain_layers[left_layer, left_pos[0], left_pos[1]] += half
            state.terrain_layers[right_layer, right_pos[0], right_pos[1]] += (material_pool - half)
            state.dirty_subsquares.update([left_pos, right_pos])
    elif left_pos:
        layer = _get_or_create_layer(state, left_pos[0], left_pos[1])
        state.terrain_layers[layer, left_pos[0], left_pos[1]] += material_pool
        state.dirty_subsquares.add(left_pos)
    elif right_pos:
        layer = _get_or_create_layer(state, right_pos[0], right_pos[1])
        state.terrain_layers[layer, right_pos[0], right_pos[1]] += material_pool
        state.dirty_subsquares.add(right_pos)


def _invalidate_tile_appearance(state: GameState, sx: int, sy: int) -> None:
    """Helper to invalidate tile/subsquare appearance cache."""
    tile_x, tile_y = sx // 3, sy // 3
    local_x, local_y = sx % 3, sy % 3


# TODO: Future tool - Widen Trench
# def widen_trench(state: GameState) -> None:
#     """Widen an existing trench by moving material from perpendicular neighbors.
#
#     Expands the trench channel by removing material from the sides and
#     redistributing it further out. Useful for creating wider water channels.
#     """
#     pass


def terrain_action(state: GameState, action: str, args: List[str]) -> None:
    """Dispatch terrain tool actions (shovel submenu)."""
    if action == "lower":
        # args[0] should be the limit layer name (e.g. "topsoil")
        limit = args[0] if args else "bedrock"
        lower_ground(state, limit)
    elif action == "raise":
        # args[0] should be the target layer name (e.g. "topsoil")
        target = args[0] if args else "topsoil"
        raise_ground(state, target)
    elif action == "trench_flat":
        dig_trench(state, "flat")
    elif action == "slope_down":
        dig_trench(state, "slope_down")
    elif action == "slope_up":
        dig_trench(state, "slope_up")
    else:
        state.messages.append(f"Unknown terrain action: {action}")


def lower_ground(state: GameState, min_layer_name: str = "bedrock") -> None:
    """Lower ground by removing material from exposed layer (array-based)."""
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sub_pos = state.get_action_target_subsquare()
    sx, sy = sub_pos

    # Find the topmost non-zero layer (exposed layer)
    exposed = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed = layer
            break

    # If no soil layers remain, allow lowering bedrock if min_layer is "bedrock"
    if exposed is None:
        if min_layer_name.lower() == "bedrock":
            # Check if we've hit minimum bedrock depth
            if state.bedrock_base[sx, sy] <= MIN_BEDROCK_ELEVATION:
                state.messages.append(f"Cannot dig deeper - bedrock floor reached ({units_to_meters(MIN_BEDROCK_ELEVATION):.1f}m)")
                return

            # Lower bedrock base (permanent terrain change)
            # NOTE: Pickaxe and shovel both share the same "cannot dig" message when hitting
            # bedrock limits. Tool-specific messages will be added during tool system refactor.
            state.bedrock_base[sx, sy] = max(MIN_BEDROCK_ELEVATION, state.bedrock_base[sx, sy] - 2)
            state.invalidate_elevation_range()
            state.terrain_changed = True
            new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
            new_elev = units_to_meters(new_elev_units)
            state.messages.append(f"Lowered bedrock by 0.2m. Elev: {new_elev:.2f}m")
            state.dirty_subsquares.add(sub_pos)
            return
        else:
            state.messages.append("Hit bedrock. Use pickaxe to break through.")
            return

    # Remove 2 units (0.2m) from the exposed layer
    current_depth = state.terrain_layers[exposed, sx, sy]
    removed = min(2, current_depth)
    state.terrain_layers[exposed, sx, sy] -= removed

    material_name = state.terrain_materials[exposed, sx, sy]

    # Clear material name if layer is now empty
    if state.terrain_layers[exposed, sx, sy] == 0:
        state.terrain_materials[exposed, sx, sy] = ""

    # Update visual and terrain flags
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()
    state.terrain_changed = True

    # Calculate new elevation (simplified - use grid bedrock_base + layers)
    new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
    new_elev = units_to_meters(new_elev_units)
    state.messages.append(f"Removed {units_to_meters(removed):.2f}m {material_name}. Elev: {new_elev:.2f}m")


def raise_ground(state: GameState, target_layer_name: str = "topsoil") -> None:
    """Raise ground by adding material to the exposed (topmost) layer (array-based)."""
    tile, subsquare, _ = state.get_target_tile_and_subsquare()
    sub_pos = state.get_action_target_subsquare()
    sx, sy = sub_pos

    cost = 0
    if state.inventory.scrap > 0:
        state.inventory.scrap -= 1
        cost = 1

    # Find the topmost non-zero layer (exposed layer)
    exposed = None
    for layer in [SoilLayer.ORGANICS, SoilLayer.TOPSOIL, SoilLayer.ELUVIATION,
                  SoilLayer.SUBSOIL, SoilLayer.REGOLITH]:
        if state.terrain_layers[layer, sx, sy] > 0:
            exposed = layer
            break

    # If no soil layers exist, add to regolith (base layer)
    if exposed is None:
        exposed = SoilLayer.REGOLITH
        # Ensure material name is set for new layer
        if not state.terrain_materials[exposed, sx, sy]:
            state.terrain_materials[exposed, sx, sy] = "gravel"  # Default regolith material

    # Add 2 units (0.2m) to the exposed layer
    state.terrain_layers[exposed, sx, sy] += 2
    material_name = state.terrain_materials[exposed, sx, sy]

    # Update visual and terrain flags
    state.dirty_subsquares.add(sub_pos)
    state.invalidate_elevation_range()
    state.terrain_changed = True

    # Calculate new elevation (simplified - use grid bedrock_base + layers)
    new_elev_units = state.bedrock_base[sx, sy] + np.sum(state.terrain_layers[:, sx, sy])
    new_elev = units_to_meters(new_elev_units)
    state.messages.append(f"Added {material_name} to surface (cost {cost} scrap). Elev: {new_elev:.2f}m")


def collect_water(state: GameState) -> None:
    tx, ty = state.get_action_target_tile()
    tile = state.tiles[tx][ty]

    # Check if any subsquare on this tile has a depot structure
    from subgrid import tile_to_subgrid
    has_depot = False
    sx_base, sy_base = tile_to_subgrid(tx, ty)
    for dx in range(SUBGRID_SIZE):
        for dy in range(SUBGRID_SIZE):
            sub_pos = (sx_base + dx, sy_base + dy)
            if sub_pos in state.structures and state.structures[sub_pos].kind == "depot":
                has_depot = True
                break
        if has_depot:
            break

    if has_depot:
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
    state.active_water_subsquares.add(state.get_action_target_subsquare())
    state.dirty_subsquares.add((sx, sy))
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

    sx, sy = state.get_action_target_subsquare()
    state.water_grid[sx, sy] += amount_units

    # Add to active set for flow simulation
    state.active_water_subsquares.add((sx, sy))
    state.dirty_subsquares.add((sx, sy))

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

        # Aggregate grid-resolution moisture (180x135) to tile resolution (60x45)
        if state.moisture_grid is not None:
            # Reshape to (60, 3, 45, 3) and average over the 3x3 subgrids
            tile_moisture = state.moisture_grid.reshape(
                state.width, SUBGRID_SIZE, state.height, SUBGRID_SIZE
            ).mean(axis=(1, 3))
        else:
            tile_moisture = np.zeros((state.width, state.height), dtype=float)

        biome_messages = recalculate_biomes(state.tiles, state.width, state.height, tile_moisture)
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

def survey_tile(state: GameState) -> None:
    """Survey tool - display grid cell information (array-based)."""
    x, y = state.get_action_target_tile()
    sub_pos = state.get_action_target_subsquare()
    sx, sy = sub_pos
    structure = state.structures.get(sub_pos)
    surface_water = state.water_grid[sx, sy]

    # Calculate elevation from grids
    from grid_helpers import get_total_elevation
    elev_m = get_total_elevation(state, sx, sy)

    desc = [f"Tile {x},{y}", f"Sub {sx%3},{sy%3}", f"elev={elev_m:.2f}m",
            f"surf={surface_water / 10:.1f}L"]

    # Get subsurface water from grid
    subsurface_total = int(np.sum(state.subsurface_water_grid[:, sx, sy]))
    if subsurface_total > 0:
        desc.append(f"subsrf={subsurface_total / 10:.1f}L")

    # Get exposed material (what the player sees on the surface)
    from grid_helpers import get_exposed_material
    material = get_exposed_material(state, sx, sy)
    desc.append(f"material={material}")

    # Get layer depths from terrain_layers grid
    topsoil_depth = state.terrain_layers[SoilLayer.TOPSOIL, sx, sy]
    organics_depth = state.terrain_layers[SoilLayer.ORGANICS, sx, sy]
    desc.append(f"topsoil={units_to_meters(topsoil_depth):.1f}m")
    desc.append(f"organics={units_to_meters(organics_depth):.1f}m")

    # Get wellspring from wellspring_grid
    wellspring_output = state.wellspring_grid[sx, sy]
    if wellspring_output > 0:
        desc.append(f"wellspring={wellspring_output / 10:.2f}L/t")

    if state.trench_grid[sx, sy]:
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
