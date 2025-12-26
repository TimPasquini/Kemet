# game_state/state.py
"""Core game state data structures."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Dict, Set, Tuple, Deque, TYPE_CHECKING

import numpy as np

from config import (
    STARTING_WATER,
    STARTING_SCRAP,
    STARTING_SEEDS,
    STARTING_BIOMASS,
    GRID_WIDTH,
    GRID_HEIGHT,
)
from world.terrain import SoilLayer
from player import PlayerState
from structures import Structure
from world.weather import WeatherSystem
from world_state import GlobalWaterPool

if TYPE_CHECKING:
    from simulation.subsurface_cache import SubsurfaceConnectivityCache

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
    """Main game state container.

    All spatial data operates on the unified 180×135 grid.
    Grid coordinates are (sx, sy) ranging from 0-179 and 0-134.
    """
    structures: Dict[Point, Structure] = field(default_factory=dict)
    player_state: PlayerState = field(default_factory=PlayerState)
    inventory: Inventory = field(default_factory=Inventory)
    weather: WeatherSystem = field(default_factory=WeatherSystem)
    messages: Deque[str] = field(default_factory=lambda: collections.deque(maxlen=100))

    # Target for actions (set by UI cursor tracking) - grid coordinates
    target_cell: Point | None = None

    # Render cache: set of (sx, sy) coordinates that need redrawing
    # Using set for O(1) add/check and automatic deduplication
    dirty_cells: Set[Point] = field(default_factory=set)

    # Simulation active sets for performance optimization
    active_water_cells: Set[Point] = field(default_factory=set)

    # Global water pool (conservation of water)
    water_pool: GlobalWaterPool = field(default_factory=GlobalWaterPool)

    # Simulation timing (accumulated time for tick processing)
    _tick_timer: float = 0.0

    # Structure lookup cache: cells that contain cisterns (for evaporation optimization)
    _cells_with_cisterns: Set[Point] = field(default_factory=set)

    # Elevation range cache (invalidated on terrain changes)
    _cached_elevation_range: Tuple[float, float] | None = None

    # === Vectorized Simulation State ===
    water_grid: np.ndarray | None = None      # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32 - surface water per cell
    elevation_grid: np.ndarray | None = None  # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=int32 - total elevation per cell
    moisture_grid: np.ndarray | None = None   # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float64 - moisture history (EMA)
    trench_grid: np.ndarray | None = None     # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=uint8 - trench markers
    kind_grid: np.ndarray | None = None       # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype='U20' - biome type per cell

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

    # === Atmosphere State (Grid-Based) ===
    # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float32. Humidity (0.1-0.9 range).
    humidity_grid: np.ndarray | None = None
    # Shape: (GRID_WIDTH, GRID_HEIGHT, 2), dtype=float32. Wind vector (x, y components).
    # wind_grid[:, :, 0] = wind_x component (-0.7 to 0.7)
    # wind_grid[:, :, 1] = wind_y component (-0.7 to 0.7)
    # Magnitude: sqrt(wind_x² + wind_y²) typically 0.0-0.7 range
    wind_grid: np.ndarray | None = None
    # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float32. Temperature multiplier.
    # Currently unused in simulation (kept at 1.0), but ready for future expansion.
    temperature_grid: np.ndarray | None = None

    # === Performance Optimization Buffers ===
    # Shape: (GRID_WIDTH, GRID_HEIGHT), dtype=float64. Pre-allocated buffer for random numbers.
    # Reused in surface flow calculations to avoid per-tick allocation.
    _random_buffer: np.ndarray | None = None

    # Subsurface connectivity cache (terrain-dependent geometric calculations)
    # Caches layer connectivity masks and contact fractions to avoid expensive
    # per-tick recalculation. Invalidated when terrain changes.
    subsurface_cache: "SubsurfaceConnectivityCache | None" = None

    # === Player convenience properties ===
    @property
    def player_cell(self) -> Point:
        """Player position in grid coordinates."""
        return self.player_state.position

    def set_target(self, cell: Point | None) -> None:
        """Set the target cell for actions from UI cursor tracking."""
        self.target_cell = cell

    def get_action_target_cell(self) -> Point:
        """Get the cell to target for actions (cursor target or player position)."""
        return self.target_cell if self.target_cell is not None else self.player_cell

    def is_cell_blocked(self, sx: int, sy: int) -> bool:
        """Check if a grid cell is blocked for movement."""
        # Bounds check
        if not (0 <= sx < GRID_WIDTH and 0 <= sy < GRID_HEIGHT):
            return True

        # Check for structure (O(1) lookup)
        if (sx, sy) in self.structures:
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
    def cell_has_cistern(self, sx: int, sy: int) -> bool:
        """Check if a cell has a cistern (O(1) lookup)."""
        return (sx, sy) in self._cells_with_cisterns

    def register_cistern(self, sx: int, sy: int) -> None:
        """Register that a cell now has a cistern. Called when cistern is built."""
        self._cells_with_cisterns.add((sx, sy))

    # === Elevation Range Cache ===
    def get_cell_kind(self, sx: int, sy: int) -> str:
        """Get the biome kind for a grid cell."""
        return self.kind_grid[sx, sy]

    def get_elevation_range(self) -> Tuple[float, float]:
        """Get cached elevation range, calculating if needed.

        Returns (min_elevation, max_elevation) across entire grid.
        """
        if self._cached_elevation_range is None:
            if self.elevation_grid is not None:
                min_elev = np.min(self.elevation_grid)
                max_elev = np.max(self.elevation_grid)
                self._cached_elevation_range = (float(min_elev), float(max_elev))
            else:
                self._cached_elevation_range = (0.0, 0.0)
        return self._cached_elevation_range

    def invalidate_elevation_range(self) -> None:
        """Mark elevation range cache as stale. Call when terrain is modified."""
        self._cached_elevation_range = None
