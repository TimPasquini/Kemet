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

### 🔴 CRITICAL - Phase 3 Blockers

#### Atmosphere System Requires Grid Vectorization
**Priority**: HIGH - Required for Phase 3 scale-up
**Current Issues**:
1. **Coarse-Grained**: 4×4 tile regions (12×12 grid cells) share identical humidity/wind values
   - Creates blocky, unnatural environmental effects
   - Prevents fine-grained environmental interactions
2. **Object-Oriented**: Uses `List[List[AtmosphereRegion]]` instead of NumPy arrays
   - Inconsistent with project's grid-based architecture
   - Prevents efficient vectorization
3. **Iterative Logic**: Python for loops in `simulate_atmosphere_tick()`
   - Misses massive parallelization opportunities
   - Slow compared to vectorized alternatives
4. **Legacy Interface**: `get_evaporation_modifier()` designed for tile-by-tile calls
   - Encourages iterative patterns in dependent code
   - Incompatible with vectorized simulation

**Required Work**:
- Migrate to grid-resolution NumPy arrays (180×135)
- Vectorize atmosphere simulation with NumPy operations
- Update evaporation to use grid-based modifiers
- Remove AtmosphereRegion class and object collections

**Files**: `atmosphere.py`, `simulation/subsurface.py`

### Performance
- **[COMPLETE]** All core simulation systems vectorized
- **[PENDING]** Atmosphere system vectorization (see above)

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

### ⚠️ Atmosphere System (Legacy - Requires Refactor)
**Status**: Functional but incompatible with Phase 3 scale-up
- Uses coarse 4×4 tile regions instead of grid resolution
- Object-oriented structure (AtmosphereRegion class)
- Iterative simulation logic
- **See "Critical Priorities" for refactor requirements**

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

### ✅ Phase 2: Geometric Trenching (COMPLETE - Dec 2025)
**Goal**: Replace boolean flags with actual geometry

**Completed**:
- Elevation unified to single source: `bedrock_base + sum(terrain_layers)`
- Three trench modes: Flat, Slope Down, Slope Up
- Material conservation with elevation-aware redistribution
- Visual highlighting system for trenching preview
- Player-relative directionality

### 🔴 Phase 3: Atmosphere Vectorization (CRITICAL - NEXT)
**Goal**: Migrate atmosphere to grid-based architecture
**Priority**: HIGH - Required before scale-up

**Current Blockers**:
1. Coarse 4×4 tile regions instead of 180×135 grid
2. Object-oriented `AtmosphereRegion` class
3. Iterative Python loops instead of vectorized operations
4. Tile-by-tile interface incompatible with vectorization

**Required Work**:
- Create `humidity_grid` (180×135) and `wind_grid` (180×135×2 for x/y components)
- Vectorize atmosphere simulation with NumPy operations
- Update evaporation to use grid-based atmospheric modifiers
- Delete `AtmosphereRegion` class and object collections
- Integrate with existing vectorized water/erosion systems

**Files to Modify**: `atmosphere.py`, `simulation/subsurface.py`, `main.py`
**Estimated Effort**: ~6-8 hours
**Benefits**: Enables Phase 4 scale-up, maintains architectural consistency, ~10-50× speedup

### Phase 4: Scale Up (AFTER Phase 3)
**Goal**: Increase map size to enable larger-scale gameplay

**Targets**:
- Initial: 512×512 grid (≈170m × 170m at 0.33m/cell)
- Stretch: 1024×1024 or 2048×2048 with active region slicing

**Prerequisites**:
- ✅ All systems vectorized
- ✅ No object collections
- 🔴 Atmosphere vectorized (Phase 3)

**Performance Strategy**:
- Active region simulation (only update areas with activity)
- Spatial partitioning for structure lookups
- LOD system for distant rendering

### Phase 5: Geological Erosion (Pre-Sim)
**Goal**: Generate realistic starting terrain through simulation

- Geological uplift simulation for bulk material generation
- Hydraulic erosion via `simulate_surface_flow` with rain cycles
- Wind erosion for exposed terrain above water
- Sediment transport and deposition based on velocity
- Conversion of heightmap/sediment to layered soil profiles

### Phase 6: Advanced Procedural Generation
**Goal**: Intelligent feature placement using advanced algorithms

**Techniques**:
- **Wave Function Collapse**: Biome transitions and micro-terrain patterns
- **Graph Grammars**: River networks and road generation
- **L-Systems**: Plant growth and branching structures

**Applications**:
- Natural-looking biome boundaries
- Realistic drainage networks
- Ancient road connections between points of interest
- Organic vegetation patterns

### Phase 7: Persistence
**Goal**: Save/Load system.
- Serialize the unified NumPy arrays (compressed).
- Serialize Player and Weather state.

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

```
kemet/
├── config.py              # Constants: Units, Time, Weather, Physics, UI
├── main.py                # GameState, tick orchestration, staggered schedule
├── world_state.py         # GlobalWaterPool, SedimentPool (conservation)
├── atmosphere.py          # AtmosphereLayer, regional humidity/wind
├── subgrid.py             # SubSquare, coordinate utils, terrain override
├── surface_state.py       # Computed appearance, unified water access
├── player.py              # Player state (sub-grid position), collision
├── camera.py              # Viewport transforms
├── mapgen.py              # Map generation, tile types (simulation props)
├── ground.py              # TerrainColumn, SoilLayer, materials
├── tools.py               # Tool system (Toolbar, Tool, ToolOption)
├── grid_helpers.py        # Clean API for grid access
├── keybindings.py         # Centralized input mappings
├── pygame_runner.py       # Pygame frontend entry point
├── simulation/
│   ├── surface.py         # Surface flow (NumPy) + seepage
│   ├── subsurface.py      # Underground flow + evaporation
│   └── erosion.py         # Overnight erosion (water/wind)
├── render/
│   ├── __init__.py        # Module exports
│   ├── map.py             # Map viewport, tiles, structures, highlights
│   ├── hud.py             # HUD panels, inventory, soil profile
│   ├── toolbar.py         # Toolbar and popup menu rendering
│   ├── overlays.py        # Help, event log, player, night overlay
│   ├── primitives.py      # Basic drawing helpers (text cache)
│   └── colors.py          # Color computation (elevation/material)
├── structures.py          # Structure ABC + Cistern, Condenser, Planter
└── ui_state.py            # UI state, layout, click regions, cursor tracking
```

---

## Testing Checkpoints

1. [x] Player renders at sub-grid position, moves in smaller increments
2. [x] Sub-grid renders, can see tile subdivisions
3. [x] Cursor highlights target sub-square within range
4. [x] Actions work at range (dig/build on target sub-square)
5. [x] Terrain modifications persist per-sub-square
6. [x] Surface water flows at sub-grid level, pools in low spots
7. [x] Water system reaches stable equilibrium
8. [x] Atmosphere affects regional evaporation
9. [x] Water conservation: pool + atmosphere + soil = closed system
10. [ ] Erosion moves material based on water velocity
11. [ ] Pre-game erosion creates interesting terrain
12. [ ] Movement constrained by elevation differences
