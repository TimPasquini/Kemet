# Kemet - Project Context for Claude

## Project Vision

Kemet is a terraforming simulation where:
- **Erosion sculpts terrain**: Starting from abundant material, water and wind carve hills, valleys, rivers, lakes.
- **Player moves dirt, doesn't create/destroy it**: Wheelbarrow → cart → bulldozer progression. (example, not firm progression)
- **Conservation of mass/water**: Core mechanic - nothing vanishes, everything goes somewhere.
- **Topology matters**: Elevation affects movement and gameplay, not just visuals.
- **Data-Oriented Simulation**: High-performance NumPy arrays drive the physics, enabling large-scale environmental interactions.

### Design Philosophy: Systems Respond Naturally

The player can place anything anywhere, but natural systems respond realistically:
- Pile organics in a stream → they wash downstream and deposit elsewhere.
- Stack sand on an exposed hilltop → wind blows it away.
- Block water flow → it pools and finds another path.

This creates emergent gameplay where understanding the systems lets you work with nature rather than against it.

### Procedural Generation Philosophy

When implementing procedural generation or algorithmic systems, prioritize approaches in this order:

1. **Wave Function Collapse (WFC)** - First choice when possible
   - Excellent for constraint-based generation
   - Produces coherent, locally-consistent results
   - Good for terrain features, biome transitions, structure placement

2. **Generative Grammars** - Second choice when WFC isn't suitable
   - L-systems for organic growth patterns (plants, rivers, erosion patterns)
   - Shape grammars for structures and settlements
   - Context-free grammars for hierarchical generation

3. **Graph Grammars** - For relational and network-based systems
   - Road/path networks
   - Water drainage systems
   - Ecosystem relationships

4. **Other Algorithms** - Use when the above don't fit
   - Perlin/Simplex noise for continuous fields
   - Cellular automata for local interactions
   - Physics simulations for realistic behavior

The goal is to create systems that generate believable, emergent complexity from simple rules rather than relying on hand-crafted content or pure randomness.

---

## Known Issues & Priorities

**Performance Optimizations Completed** (Dec 25, 2025):
1. ✅ Pre-allocated random buffer in simulation/surface.py (eliminates per-tick allocation)
2. ✅ Verified edge runoff water conservation is correct (no bug found)
3. ✅ Vectorized elevation percentile calculation in recalculate_biomes using np.argsort
4. ✅ Optimized tick_structures to avoid unnecessary list() conversion
5. ✅ pygame.surfarray for water rendering (direct pixel manipulation via array slicing)
6. ✅ Replaced dict-based percentiles with array-based for O(1) access

**Note**: These were micro-optimizations. Profile to measure actual impact.

### ✅ Architecture Complete - All Systems Vectorized

**Status**: 100% pure NumPy grid architecture achieved
- **[COMPLETE]** All core simulation systems vectorized
- **[COMPLETE]** Atmosphere system vectorized (Phase 3)
- **[COMPLETE]** Grid-based evaporation with atmospheric modifiers
- **[COMPLETE]** Wind exposure calculation vectorized

### UI/UX
- **Dead Space**: Map feels crowded; consider HUD overlay with floating windows
---

## Architecture Overview

### Current Architecture: Pure Grid-Based (Data-Oriented)

**Complete as of 2025-12-24**: All simulation state lives in NumPy arrays. Tile and SubSquare classes have been completely removed.

#### Core Simulation Grids (180×135 subsquare resolution)
*   `water_grid` - Surface water (int32)
*   `elevation_grid` - Total elevation (int32, computed as `bedrock_base + sum(terrain_layers)`)
*   `terrain_layers` - Soil layer depths (6 layers × 180 × 135, int32)
*   `bedrock_base` - Bedrock elevation baseline (180 × 135, int32)
*   `terrain_materials` - Material names per layer (6 layers × 180 × 135, str)
*   `subsurface_water_grid` - Underground water (6 layers × 180 × 135, int32)
*   `kind_grid` - Biome types (180 × 135, str)
*   `wellspring_grid` - Wellspring output rates (180 × 135, int32)
*   Material property grids: `porosity_grid`, `permeability_vert_grid`, `permeability_horiz_grid`

#### Architecture Principles
*   **Single Truth**: All simulation state in NumPy arrays
*   **No Object Collections**: Tile and SubSquare classes deleted (Dec 24, 2025)
*   **Vectorized Physics**: Water, erosion, and biome systems run as array operations
*   **Geometry-First**: All features (trenches, structures) are geometric, not boolean flags
*   **Tile-Level Aggregation**: 3×3 grid cells per tile for organization (60×45 tiles = 180×135 grid)

### Water Conservation System

Water flows in a closed cycle via `GlobalWaterPool`:

```
Wellsprings ←──── total_volume ←──── Edge Runoff
    │                                      ↑
    ↓                                      │
Soil/Surface ──→ Evaporation ──→ atmospheric_reserve ──→ Rain

```
- **Wellsprings** draw from finite pool (not infinite)
- **Edge runoff** returns water to pool (not lost)
- **Evaporation** moves water to atmosphere (returns via rain)
---

## Visual Design Philosophy

The rendering style should intuitively communicate the nature of game elements.

1. **Objects (e.g., Structures):** Rendered as distinct items *on top of* the terrain. This communicates they are interactable and occupy space.

2. **Terrain Features (e.g., Trenches):** Rendered as modifications *of* the terrain itself (e.g., a border). This communicates they are passive alterations.

This helps players categorize "things I built" vs. "ways I've shaped the land."

---

## Confirmed Design Decisions

- [x] Actions at range: **Yes** (act on target without moving)
- [x] Upward seepage: **Elevation-weighted** distribution
- [x] Water conservation: **Closed system** via GlobalWaterPool
- [x] Simulation scheduling: **Staggered** to spread CPU load

---

## Implementation Status

### ✅ Grid Architecture Complete (Dec 2025)
- All simulation state in NumPy arrays (180×135 grid resolution)
- Tile and SubSquare classes completely removed
- All physics fully vectorized (water, erosion, biomes)
- Geometric trenching with three slope modes
- Water conservation via GlobalWaterPool
- Player interaction at range with cursor targeting

### ✅ Atmosphere System (Vectorized - Phase 3 Complete)
**Status**: Fully vectorized grid-based implementation
- Uses `humidity_grid` (180×135) and `wind_grid` (180×135×2) at full grid resolution
- Pure NumPy vectorized operations with Gaussian diffusion
- Runs every 2 ticks for performance optimization
- Located in `simulation/atmosphere.py` (133 lines of clean vectorized code)

### 🧹 Legacy Code Cleanup (Complete - Dec 25, 2025)
**Completed**:
- All Tile/SubSquare class references removed
- Deleted `surface_state.py` (broken legacy code)
- Marked `atmosphere.py`, `subgrid.py`, `TerrainColumn` for deprecation
- Updated 500+ lines of documentation
- Fixed all misleading comments about architecture
- All TYPE_CHECKING imports cleaned up
- All function signatures updated to remove deprecated parameters
- **Dec 25, 2025**: Final terminology cleanup
  - Renamed `tile_evaps` → `cell_evaps`, `sub_evaps` → `final_evaps` in subsurface.py
  - Renamed all `sub_x`/`sub_y` → `sx`/`sy` throughout codebase (5 files, 52 lines)
  - Removed "SubSquare" references from comments
  - Standardized on `sx, sy` convention for grid cell coordinates

---

## Roadmap

### ✅ Phase 1: Grid Unification (COMPLETE - Dec 2025)
**Goal**: Pure NumPy grid architecture with no object collections

**Completed**:
- All simulation state migrated to NumPy grids
- Tile and SubSquare classes completely deleted (Dec 24)
- All physics vectorized (water, erosion, biomes)
- Water conservation via GlobalWaterPool
- 250× speedup on auxiliary calculations
- 1000+ lines of code removed

### ✅ Phase 2: Geometric Trenching & Legacy Cleanup (COMPLETE - Dec 2025)
**Goal**: Replace boolean flags with actual geometry and remove all legacy code

**Completed**:
- Elevation unified to single source: `bedrock_base + sum(terrain_layers)`
- Three trench modes: Flat, Slope Down, Slope Up
- Material conservation with elevation-aware redistribution
- Visual highlighting system for trenching preview
- Player-relative directionality
- **Legacy Code Cleanup**:
  - Deleted `surface_state.py` (broken, referenced deleted classes)
  - Removed all Tile/SubSquare class references from TYPE_CHECKING imports
  - Removed deprecated parameters from all functions
  - Marked `atmosphere.py`, `subgrid.py`, `TerrainColumn` for Phase 3 deprecation
  - Updated 500+ lines of documentation to reflect grid-based architecture
  - Fixed all misleading comments about "tiles" vs "grid cells"

### ✅ Phase 3: Atmosphere Vectorization (COMPLETE - Dec 2025)
**Goal**: Migrate atmosphere to grid-based architecture to close out grid migration

**Completed**:
- Created `humidity_grid` (180×135) and `wind_grid` (180×135×2 for x/y components)
- Vectorized atmosphere simulation with NumPy operations and Gaussian diffusion
- Updated evaporation to use grid-based atmospheric modifiers
- Vectorized wind exposure calculation in erosion
- Migrated `atmosphere.py` to `simulation/atmosphere.py` with pure grid operations
- Legacy `atmosphere.py` and `subgrid.py` deleted from main directory
- Integration complete in `simulation/subsurface.py` and `simulation/erosion.py`

**Results Achieved**:
- 100% pure grid architecture (no object collections anywhere)
- ~10-50× atmosphere speedup via vectorization
- 300+ lines of legacy code removed
- Ready for Phase 4 scale-up

### ✅ Phase 3.5: Code Reorganization (COMPLETE - Dec 2025)
**Goal**: Reorganize codebase for better maintainability with clean grid-based code

**Completed Step A: Game State Module**
Created `game_state/` subdirectory:
- `state.py` - GameState dataclass
- `initialization.py` - build_initial_state()
- `terrain_actions.py` - dig_trench, lower/raise_ground
- `player_actions.py` - collect/pour_water, survey

**Completed Step B: World Generation Module**
Created `world/` subdirectory:
- `generation.py` - World generation (formerly mapgen.py)
- `biomes.py` - Biome calculation logic
- `terrain.py` - Terrain data structures (formerly ground.py)
- `weather.py` - Weather system

**Results Achieved**:
- main.py reduced to 180 lines (simulation loop + orchestration)
- Clear module boundaries: game_state/, world/, simulation/, render/
- Excellent code organization and navigation
- All systems cleanly separated

### ✅ Phase 4: Performance Baseline & Scale-Up Testing (COMPLETE - Dec 2025)

**Goal**: Validate performance and test scalability of vectorized architecture

**Status**: ✅ COMPLETE - Architecture validated with excellent results

**Completed Work Items**:
1. ✅ **Performance Baseline**
   - Profiled 180×135 grid: 24.3 TPS, 41ms avg tick, 18 MB memory
   - Identified hot paths: subsurface flow (37%), evaporation (16%), surface flow (15%)
   - Documented comprehensive baseline metrics

2. ✅ **Scaling Tests**
   - 360×270 (4× cells): 9.0 TPS, 111ms avg tick, 70 MB - **27% better than linear**
   - 512×512 (10.8× cells): 3.5 TPS, 287ms avg tick, 188 MB - **36% better than linear**
   - All systems functional at all scales
   - Water conservation maintained across all sizes

3. ✅ **Performance Analysis**
   - Sub-linear scaling achieved (vectorization working excellently)
   - Memory scales perfectly linearly
   - No optimization needed for baseline 180×135
   - Optional optimization strategies documented for 512×512 if needed

**Key Results**:
- ✅ **Sub-linear performance scaling** - 27-36% better than expected
- ✅ Perfect linear memory scaling (~720 bytes/cell constant)
- ✅ All systems working correctly at all grid sizes
- ✅ 180×135 baseline achieves 45-50 FPS projected (excellent)
- ✅ 360×270 achieves 20-25 FPS projected (playable)
- ⚠️ 512×512 achieves 8-12 FPS projected (needs active region optimization)

**Documentation**:
- All performance tools consolidated in `performance/` module
- See `performance/README.md` for comprehensive usage guide

**Recommendations**:
- Implement active region optimization since 2560×1600 is the target design goal

## Performance Tools

All performance tooling is in `performance/`:

**Benchmarks** (`performance/benchmarks/`):
- `simulation.py` - Simulation performance (headless)
- `rendering.py` - Rendering performance (NEW in Phase 4.5)
- `integrated.py` - Combined sim + render (NEW in Phase 4.5)
- `utils.py` - Shared utilities for timing and formatting

**Profilers** (`performance/profilers/`):
- `subsurface.py` - Detailed subsurface profiling
- `rendering.py` - Detailed rendering profiling (NEW in Phase 4.5)

**Reports** (`performance/reports/`):
- `simulation_scaling.md` - Scaling analysis across grid sizes
- `phase4_summary.md` - Phase 4 completion summary
- `rendering_performance.md` - Rendering benchmark results (generated)

See `performance/README.md` for detailed usage and CLI examples.

### ✅ Phase 4.5: Reorganization Completion (COMPLETE - Dec 2025)
**Goal**: Complete code reorganization now that scale-up is validated
**Status**: ✅ COMPLETE

**✅ Performance Module (Parts 1-7)**:
- All benchmarking tools consolidated in `performance/` directory
- Rendering benchmarks and profilers added (NEW)
- Integrated simulation + rendering benchmarks (NEW)
- Comprehensive documentation in performance/README.md

**✅ Core Module (Part 8 - Step C)**:
- Created `core/` subdirectory with config.py, grid_helpers.py, camera.py, utils.py
- Updated 30+ files with import changes
- Git history preserved

**✅ Interface Module (Part 9 - Step D)**:
- Created `interface/` subdirectory with player.py, ui_state.py, tools.py, keybindings.py
- Updated 10+ files with import changes
- Git history preserved

**✅ Cleanup (Part 10)**:
- Moved apply_surface_evaporation() to simulation/surface.py
- Deleted simulation/subsurface.py

**Results Achieved**:
- Main directory reduced to 4 core files + organized submodules
- Clear separation of concerns (core, interface, performance, game_state, world, simulation, render)
- All performance tools working with comprehensive documentation
- No performance regressions (143 FPS rendering, 24.5 TPS simulation)

### ✅ Phase 4.75: Critical Bug Fixes (COMPLETE - Dec 2025)
**Goal**: Fix rendering and generation issues before scale-up work
**Status**: ✅ COMPLETE

**Issues Fixed**:
1. ✅ **Water Rendering Misalignment** (render/map.py)
   - **Problem**: Water overlay misaligned at certain zoom levels, jittered 1-2 pixels up/left
   - **Root Cause**: Creating massive surfaces at CELL_SIZE scale when zoomed out caused both alignment and performance issues
   - **Solution**: Implemented adaptive resolution water rendering
     - Scale factor: `max(4, int(CELL_SIZE * min(1.0, camera.zoom)))`
     - At zoom 0.25×: 12px per cell (vs 48px), reducing pixels by 16×
     - Scale-adjusted coordinate transformation maintains pixel-perfect alignment
   - **Result**: Perfect alignment at all zoom levels + 16× performance improvement when zoomed out

2. ✅ **Elevation Generation Problems** (world/generation.py)
   - **Problem**: Terrain rarely above sea level, max ~0.5m elevation
   - **Solution**: Multi-part fix
     - Raised bedrock baseline from `random.uniform(-2.5, -2.0)` to `random.uniform(0.0, 1.0)`
     - Increased soil depth ranges: dunes 2.5-4.5m, flat 1.5-2.5m, wadis 0.8-1.8m
     - Added gaussian-filtered noise with non-linear transformation (`elevation_modifier ** 1.5`)
     - Applied -1m to +2m bedrock variation for dramatic peaks and valleys
   - **Result**: Realistic terrain with varied elevation, all naturally above sea level

3. ✅ **Water Distribution Oscillation** (simulation/config.py, simulation/surface.py)
   - **Problem**: Water oscillated between cells creating unstable equilibrium
   - **Solution**: Flow damping + threshold
     - Reduced SURFACE_FLOW_RATE from 50% to 30%
     - Implemented SURFACE_FLOW_THRESHOLD of 5 units (prevents micro-flow oscillation)
   - **Result**: Stable water distribution with natural settling behavior

4. ✅ **Refactor Opportunities**
   - **TYPE_CHECKING imports**: Moved all TYPE_CHECKING imports from inside functions to top of files (simulation/surface.py, render/hud.py, structures.py, world/generation.py)
   - **pygame_runner.py event handling**: Refactored 133-line event loop into 5 helper functions:
     - `handle_quit_event()`, `handle_mouse_wheel_event()`, `handle_zoom_keys_event()`
     - `handle_mouse_click_event()`, `handle_keyboard_event()`
   - **Trenching tool comments**: Added comprehensive docstrings to all trenching modes explaining intent, strategy, and material flow logic
   - **Material property grid vectorization** (game_state/initialization.py): Replaced triple-nested Python loops with vectorized NumPy mask-based assignment

5. ✅ **Overnight Erosion Investigation** (simulation/erosion.py)
   - **Finding**: `apply_overnight_erosion()` is active and called, but wind erosion is disabled
   - **Reason**: Wind erosion requires optimization (currently too expensive for real-time)
   - **Documentation**: Added comment explaining wind erosion is pending Phase 5 optimization
   - **Status**: No changes needed, intentionally disabled for performance

**Additional Fixes**:
- ✅ **Humus Distribution**: Fixed organics appearing everywhere; now 0% default, 2% only in wadis
- ✅ **Soil Meter Auto-Scaling** (render/hud.py):
  - Implemented auto-scaling anchored to sea level at 60% down panel
  - Always includes sea level in range as reference floor
  - Caps zoom at 1.5× default for consistency
  - Bedrock extended to fill panel bottom (eliminates black deadspace)

**Performance Validation**:
- Ran comprehensive rendering benchmark (600 frames, 6 zoom levels)
- Results: 285.8 FPS average, 100% frames under 16.67ms target
- Worst case (0.25× zoom, 4100 cells): 224 FPS, 4.46ms/frame
- See `performance/BENCHMARK_HISTORY.md` for detailed metrics

**Files Modified**:
- render/map.py (adaptive water rendering)
- render/hud.py (soil meter auto-scaling, TYPE_CHECKING imports)
- world/generation.py (terrain generation, TYPE_CHECKING imports)
- simulation/config.py (flow parameters)
- simulation/surface.py (flow threshold, TYPE_CHECKING imports)
- game_state/initialization.py (vectorized material grids)
- game_state/terrain_actions.py (trenching comments)
- pygame_runner.py (event handling refactor)
- structures.py (TYPE_CHECKING imports)
- simulation/erosion.py (wind erosion documentation)
- performance/benchmarks/rendering.py (added 0.25× zoom to suite)

### Phase 5: Scale-Up & Optimization (Massive Maps)
**Goal**: Enable gigantic maps (2560×1600 cells) through optimization and chunking
**Priority**: High - Fundamental to game concept. Geology happens on a large scale.

**Approach**: Optimize first, then derive architecture from data

**Step A: Subsurface Optimization Investigation**
- Subsurface simulation is the most limiting factor (89% of subsurface time in horizontal flow)
- Investigate methods to more efficiently calculate water transfers
- Investigate decoupling water movements from "atomic" application to spread over ticks
  - Gravity flow → lateral flow → capillary flow?
- Experiment with less frequent updates (water moves slowly underground)
- Profile and measure impact of each optimization

**Step B: Determine Optimal Active Play-Space**
- Use performance benchmarks to test different active region sizes
- Measure TPS at various active region dimensions (256×256, 512×512, 768×768, etc.)
- Find sweet spot: largest area that maintains 30+ TPS
- This becomes the foundation for chunking architecture

**Step C: Derive Chunk Architecture from Data**
- Based on optimal active play-space size, design chunk system
- Determine chunk size (e.g., if 512×512 is optimal, use 256×256 chunks)
- Implement chunked simulation (only simulate active chunks)
- Implement chunked rendering (viewport-based, only render visible chunks)
- Design chunk loading/unloading system

**Step D: Viewport Rendering & Chunked Backgrounds**
- Only render visible tiles instead of entire world
- Chunked background caching (e.g., 256×256 cell chunks)
- Camera zoom optimization with cached backgrounds
- Enable massive maps without GPU texture limit issues

**Expected Outcomes**:
- Ability to run maps at global scale (2560×1600+ cells)
- Simulation focused on active region around player
- Rendering limited to visible viewport
- Foundation for world-gen and embark system (like Dwarf Fortress)

### Phase 6: Geological Erosion & World Generation
**Goal**: Generate realistic starting terrain through simulation and procedural generation

**Geological Pre-Simulation**:
- Geological uplift simulation for bulk material generation
- Hydraulic erosion via `simulate_surface_flow` with rain cycles
- Wind erosion for exposed terrain above water
- Sediment transport and deposition based on velocity
- Conversion of heightmap/sediment to layered soil profiles

**Advanced Procedural Generation**:
- **Wave Function Collapse**: Biome transitions and patterns
- **Graph Grammars**: River networks, drainage systems, and road generation
- **L-Systems**: Plant growth and branching structures
- Natural-looking biome boundaries
- Realistic drainage networks
- Ancient road connections between points of interest
- Organic vegetation patterns

**World-Gen & Embark System** (like Dwarf Fortress):
- Generate global-scale maps (2560×1600+ cells)
- Multi-scale simulation (global → regional → local)
- Player selects starting location (embark site)
- Only active region simulated during gameplay

**Theoretical System for a Cascading Constraint System**
- Simulation begins at the global level and should manage the formation of primary landmass and features
- global features, like rivers or mountains, set constraints for the regional scale which is a bit more detailed
- The region needs to solve around the feature that existed at the macro scale
    -     A river on the global needs to have a river on the region that follows roughly the same course
    -     A mountain in the north east corner of the region on the global scale has high elevation in the top right corner
    -     Other things might be oasis, villages, forts, and geological phenomenon
    -     These features are constraints around which the WFC solves to set biomes
    -     A local scale (embark site) might be the shore of the river or the foot of the hill 
    -     This is a desert planet inspired by Dune and Tatooine, at the end of worldgen, rivers should be shallow and ephemeral


### Phase 7: Persistence
**Goal**: Save/Load system
- Serialize the unified NumPy arrays (compressed)
- Serialize Player and Weather state
- Support for chunked world saves (only save modified chunks)

---

## Key Implementation Notes

### Water Transfer Functions
- `simulate_surface_flow()` - Horizontal flow between sub-squares (Vectorized)
- `simulate_surface_seepage()` - Downward into topmost soil layer
- `simulate_vertical_seepage()` - Between soil layers + capillary rise
- `distribute_upward_seepage()` - Elevation-weighted distribution to sub-squares

### Render Caching System
```python
# Static terrain pre-rendered (in pygame_runner.py)
background_surface = render_static_background(state, font)

# Dirty tracking uses coordinate tuples (pygame-agnostic)
state.dirty_subsquares: List[Point]

# When terrain changes, mark dirty and regenerate
state.dirty_subsquares.append((sub_x, sub_y))
background_surface = update_dirty_background(background_surface, state, font)
```

Dynamic elements (water, player, structures) render on top each frame.

### NumPy Integration
The surface simulation is now fully data-oriented. The `water_grid` and `elevation_grid` are the sources of truth for the physics calculations. The expensive `sync_objects_to_arrays` and `sync_arrays_to_objects` functions have been removed, eliminating a major performance bottleneck. The `terrain_changed` flag is used to trigger rebuilds of the `elevation_grid` only when necessary.

---

## Water Balance (Current Tuning)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Initial water pool | 100,000 units | 10,000L in global pool |
| Primary wellspring | 40-60 units/tick | Draws from pool |
| Secondary wellspring | 15-30 units/tick | Draws from pool |
| Surface flow rate | 50% | Per tick transfer |
| Surface seepage rate | 15% | Infiltration to soil |
| Capillary rise rate | 5% | Slow upward movement |

---

## File Structure

### Current Structure (Phase 4.5 Performance Module - Dec 2025)
```
kemet/
├── config.py              # Constants: Units, Time, Weather, Physics, UI
├── main.py                # Simulation loop + orchestration (180 lines)
├── world_state.py         # GlobalWaterPool, SedimentPool (conservation)
├── player.py              # Player state (grid position), collision
├── camera.py              # Viewport transforms
├── tools.py               # Tool system (Toolbar, Tool, ToolOption)
├── grid_helpers.py        # Clean API for grid access
├── keybindings.py         # Centralized input mappings
├── pygame_runner.py       # Pygame frontend entry point
├── structures.py          # Structure ABC + Cistern, Condenser, Planter
├── ui_state.py            # UI state, layout, click regions, cursor tracking
├── utils.py               # General utilities
├── game_state/            # Game state management (Phase 3.5)
│   ├── state.py           # GameState dataclass
│   ├── initialization.py  # build_initial_state()
│   ├── terrain_actions.py # Terrain manipulation
│   └── player_actions.py  # Player actions
├── world/                 # World generation & environment (Phase 3.5)
│   ├── generation.py      # Map generation (formerly mapgen.py)
│   ├── biomes.py          # Biome calculation
│   ├── terrain.py         # Terrain data (formerly ground.py)
│   └── weather.py         # Weather system
├── simulation/            # Physics simulation
│   ├── atmosphere.py      # Grid-based atmosphere (vectorized, Phase 3)
│   ├── surface.py         # Surface flow (vectorized) + seepage
│   ├── subsurface.py      # Underground flow + evaporation
│   ├── subsurface_vectorized.py  # Vectorized subsurface simulation
│   ├── erosion.py         # Overnight erosion (water/wind)
│   └── config.py          # Simulation constants
├── render/                # All rendering
│   ├── __init__.py        # Module exports
│   ├── map.py             # Map viewport rendering
│   ├── hud.py             # HUD panels, inventory, soil profile
│   ├── toolbar.py         # Toolbar and popup menu rendering
│   ├── overlays.py        # Help, event log, night overlay
│   ├── minimap.py         # Minimap rendering
│   ├── player_renderer.py # Player rendering
│   ├── primitives.py      # Basic drawing helpers
│   ├── colors.py          # Color computation
│   ├── grid_helpers.py    # Grid rendering utilities
│   └── config.py          # Rendering constants
└── performance/           # Performance benchmarking & profiling (Phase 4.5)
    ├── README.md          # Comprehensive usage guide
    ├── benchmarks/        # High-level performance benchmarks
    │   ├── simulation.py  # Simulation tick performance (headless)
    │   ├── rendering.py   # Rendering frame performance
    │   ├── integrated.py  # Combined sim + render benchmarks
    │   └── utils.py       # Shared utilities (Timer, formatting, etc.)
    ├── profilers/         # Detailed profiling with hierarchical breakdowns
    │   ├── subsurface.py  # Subsurface simulation profiling
    │   └── rendering.py   # Rendering pipeline profiling
    └── reports/           # Generated performance reports
        ├── simulation_scaling.md  # Simulation scaling analysis
        ├── phase4_summary.md      # Phase 4 completion summary
        └── rendering_performance.md  # Rendering benchmarks (generated)
```

### Target Structure After Steps C & D (Phase 4.5 Complete)
```
kemet/
├── main.py                # Simulation loop + command dispatch (~300 lines)
├── structures.py          # Structure definitions
├── world_state.py         # Conservation systems
├── pygame_runner.py       # Pygame frontend entry point
├── game_state/            # ✅ Game state management (Phase 3.5)
│   ├── state.py           # GameState dataclass
│   ├── initialization.py  # build_initial_state()
│   ├── terrain_actions.py # Terrain manipulation
│   └── player_actions.py  # Player actions
├── world/                 # ✅ World generation & environment (Phase 3.5)
│   ├── generation.py      # Map generation (was mapgen.py)
│   ├── biomes.py          # Biome calculation
│   ├── terrain.py         # Terrain data (was ground.py)
│   └── weather.py         # Weather system
├── simulation/            # Physics simulation
│   ├── surface.py
│   ├── subsurface_vectorized.py
│   ├── erosion.py
│   └── config.py
├── render/                # All rendering
├── performance/           # ✅ Performance tools (Phase 4.5)
│   ├── benchmarks/
│   ├── profilers/
│   └── reports/
├── core/                  # TODO - Core utilities (Step C)
│   ├── config.py
│   ├── grid_helpers.py
│   ├── camera.py
│   └── utils.py
└── interface/             # TODO - Player interaction (Step D)
    ├── player.py
    ├── ui_state.py
    ├── tools.py
    └── keybindings.py
```