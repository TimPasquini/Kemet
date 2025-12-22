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

## Known Issues & Watchlist

### Performance
- **[PARTIALLY SOLVED] Performance**: The `sync_objects_to_arrays` bottleneck has been eliminated for the surface water simulation by migrating state to global NumPy arrays. Subsurface simulation still uses a hybrid model.

### Gameplay/Simulation
- **Water Bias**: Historical issue where water favored bottom-right flow. Mitigated by probabilistic rounding in NumPy implementation, but requires monitoring.
- **Resolution Mismatch**: Subsurface (Tile) vs Surface (SubSquare) resolution causes logical disconnects (e.g., localized infiltration spreads to whole tile). *To be solved by Unification.*

### UI/UX
- **[SOLVED] Navigation**: Minimap and Zoom implemented.
- **[SOLVED] No clock**: Hard to know time of day.
- **Feedback**: "Trench" status is a boolean flag, visually distinct but physically "magic" (reduces evap without geometry). *To be solved by Geometric Trenches.*
- **Dead Space**: Map feels crowded; consider HUD overlay with floating windows
---

## Architecture Overview

### Current State: Hybrid Object-Array Model

The codebase is in transition from a pure Object-Oriented model to a Data-Oriented (NumPy) model.

1.  **Storage (Objects)**:
    *   `Tile` (60x45): Holds `TerrainColumn`, `WaterColumn`, `AtmosphereRegion`.
    *   `SubSquare` (180x135): Holds `elevation_offset` and other transient state. `surface_water` and `has_trench` have been migrated to global NumPy arrays.
2.  **Simulation (Arrays)**:
    *   Surface flow is calculated on 180x135 `int32` NumPy grids (`water_grid`, `elevation_grid`).
    *   `water_grid` and `trench_grid` are now the single source of truth for surface simulation, eliminating the object-array sync step for those properties.
    *   **[NEW]** Unified terrain arrays (`terrain_layers`, `bedrock_base`, `elevation_offset_grid`) and `subsurface_water_grid` are initialized and populated, serving as a shadow state ready for the physics rewrite.
    *   **[NEW]** Terrain modification tools now write to both the object graph and the unified arrays to maintain synchronization.

### Target State: Unified Grid (Data-Oriented)
*   **Single Truth**: All simulation state lives in global NumPy arrays (180x135 currently, potentially 1024x1024 or 2048x2048).
*   **No Objects**: `Tile` and `SubSquare` classes are removed or become transient render helpers.
*   **Vectorized Physics**: All systems (Water, Wind, Erosion, Plants) run as array operations.
*   **Geometry-First**: Features like trenches are geometric depressions, not boolean flags.

### Simulation Pipeline (Staggered)

Tick operations are spread across a 4-tick cycle to avoid spikes:

```
tick % 4 == 0: Surface flow (~35ms) + evaporation (~5ms)
tick % 4 == 1: Seepage + moisture (~15ms) + SUBSURFACE (~65ms) + evaporation
tick % 4 == 2: Surface flow (~35ms) + evaporation (~5ms)
tick % 4 == 3: Seepage + moisture (~15ms) + evaporation (~5ms)
```

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

### Sub-Grid Model (3x3)

Each simulation tile contains 9 **sub-squares**:
```
+---+---+---+
|0,0|1,0|2,0|  <- Sub-squares within one tile
+---+---+---+
|0,1|1,1|2,1|
+---+---+---+
|0,2|1,2|2,2|
+---+---+---+
```

**Sub-square data:**
- `elevation_offset: float` - Height relative to tile base (meters)
- `structure_id: Optional[int]` - Structure occupying this sub-square
- `trench_grid`: A global boolean grid indicates trench presence.
- `terrain_override: Optional[TerrainColumn]` - Per-sub-square terrain modifications
- `water_passage: float` - Daily accumulator for erosion calculations
- `wind_exposure: float` - Daily accumulator for wind erosion

**Coordinate system:**
- World sub-coords: `(tile_x * 3 + sub_x, tile_y * 3 + sub_y)`
- For 60x45 tile map → 180x135 sub-square map
- Player position: sub-square coordinates

---

## Visual Design Philosophy

The rendering style should intuitively communicate the nature of game elements.

1. **Objects (e.g., Structures):** Rendered as distinct items *on top of* the terrain. This communicates they are interactable and occupy space.

2. **Terrain Features (e.g., Trenches):** Rendered as modifications *of* the terrain itself (e.g., a border). This communicates they are passive alterations.

This helps players categorize "things I built" vs. "ways I've shaped the land."

---

## Confirmed Design Decisions

- [x] Sub-grid size: **3x3** per tile
- [x] Player movement: **Sub-grid level**
- [x] Range calculation: **Chebyshev distance** (square range)
- [x] Actions at range: **Yes** (act on target without moving)
- [x] Surface water: **Sub-grid level** (stored per sub-square)
- [x] Surface flow: **8-neighbor** (cardinal + diagonal)
- [x] Sub-squares: **Independent units** - tile boundaries invisible to flow
- [x] Upward seepage: **Elevation-weighted** distribution
- [x] Terrain modifications: **Per-sub-square** via `terrain_override`
- [x] Water conservation: **Closed system** via GlobalWaterPool
- [x] Simulation scheduling: **Staggered** to spread CPU load

---

## Implementation Status

### Phase 1: Sub-Grid Foundation - COMPLETE
Player moves on 180x135 grid, interaction range highlights work, cursor targeting functional.

### Phase 2: Surface Water on Sub-Grid - COMPLETE
- Surface water stored per sub-square
- 8-directional flow based on elevation + water depth
- Surface-to-soil seepage implemented
- Elevation-weighted upward seepage (capillary rise, overflow)

### Phase 2.5: Unified Layer System - COMPLETE
- Created `surface_state.py` with computed appearance system
- Removed stored `SubSquare.biome` - now computed from terrain/water state
- Unified water access helpers

### Phase 3: Atmosphere Layer - COMPLETE
- Created `atmosphere.py` with regional humidity/wind
- Regions cover 4x4 tiles with humidity, wind direction/speed
- Integrated into evaporation calculation
- Atmosphere evolves over time based on heat

### Phase 4: Water Conservation - COMPLETE
- Created `world_state.py` with `GlobalWaterPool`
- Wellsprings draw from finite pool
- Edge runoff returns to pool
- Evaporation routes to atmospheric reserve

### Phase 5: Erosion System - PAUSED
- Overnight erosion using accumulated daily pressures
- Water passage and wind exposure tracking
- *Paused to prioritize architectural unification*

### Completed Optimization
- Refactored surface water simulation to use NumPy.
- Vectorized gradient and flow calculations
- Migrated `surface_water` and `has_trench` state to global NumPy arrays (`water_grid`, `trench_grid`), making them the single source of truth and eliminating the object-array sync bottleneck for surface simulation.


---

## Roadmap: The Great Unification

The immediate technical goal is to complete the transition to a fully vectorized system.
### Phase 1: Unification (In Progress)
**Goal**: Eliminate `Tile` and `SubSquare` as primary simulation units. Move all state to global arrays.
- **[DONE]** `has_trench` migrated to `trench_grid`.
- **[DONE]** `surface_water` migrated to `water_grid`, eliminating `sync_objects_to_arrays`.
- **[DONE]** Unified terrain arrays (`terrain_layers`, `bedrock_base`, `elevation_offset_grid`) initialized and populated.
- **[DONE]** Unified `subsurface_water_grid` initialized and populated.
- **[DONE]** Terrain modification tools sync to unified arrays.
- **Unified Grid**: 180x135 (or larger) becomes the single source of truth.
- **Unified Layers**: `TerrainColumn` becomes a dictionary of arrays (`bedrock_grid`, `sand_grid`, `organics_grid`).
- **Unified Atmosphere**: Atmosphere becomes 180x135 arrays (`humidity_grid`, `wind_grid`), allowing micro-climates and occlusion.
- **Benefit**: Removes the expensive sync step, enables massive map scaling.

### Phase 2: Geometric Trenches
**Goal**: Replace `has_trench` flag with actual geometry.
- **Digging**: Removes material from the `topsoil` array, lowering the `elevation` array.
- **Physics**: Water flows into the hole naturally due to gravity.
- **Shelter**: Evaporation is calculated using "Wind Occlusion" (raymarching or neighbor checks on the elevation grid) rather than magic flags.

### Phase 3: Scale Up
**Goal**: Increase map size once performance overhead is removed.
- Target: 512x512 (approx 170m x 170m).
- Potential for 1024x1024 or 2048x2048 with active region slicing.

### Phase 4: Geological Erosion (Pre-Sim)
**Goal**: Generate realistic starting terrain.
- **Bulk Material**: Generate initial volume using noise functions (not perlin/simplex, but geological uplift simulation).
- **Hydraulic Erosion**: Run `simulate_surface_flow` with `rain=True` for N cycles.
- **Wind Erosion**: Should run against map areas that are above water.
- **Resolution**: Where velocity is high -> `elevation -= sediment`. Where low -> `elevation += sediment`.
- **Conversion**: Convert resulting heightmap/sediment map into soil layers.

### Phase 4.5: Procedural Generation Strategy
**Goal**: Intelligent placement of features using advanced algorithms.
- **Graph Grammars**: Use for river network generation and connecting "Locations of Note" with ancient roads.
- **L-Systems**: Use for procedural plant growth and branching structures.
- **Wave Function Collapse**: Use for biome texture synthesis and micro-terrain transitions (e.g., Sand -> Dunes -> Rock).

### Phase 5: Persistence
**Goal**: Save/Load system.
- Serialize the unified NumPy arrays (compressed).
- Serialize Player and Weather state.

---

## Key Implementation Notes

### Coordinate Conversion
```python
def tile_to_subgrid(tile_x, tile_y):
    return (tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE)

def subgrid_to_tile(sub_x, sub_y):
    return (sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE)
```

### Water Transfer Functions
- `simulate_surface_flow()` - Horizontal flow between sub-squares (Vectorized)
- `simulate_surface_seepage()` - Downward into topmost soil layer
- `simulate_vertical_seepage()` - Between soil layers + capillary rise
- `distribute_upward_seepage()` - Elevation-weighted distribution to sub-squares

### Terrain Override Pattern
```python
# Get terrain for a sub-square (uses override if exists)
terrain = get_subsquare_terrain(subsquare, tile.terrain)

# Create override before modifying sub-square terrain
ensure_terrain_override(tile, local_x, local_y)
```

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
├── water.py               # WaterColumn (subsurface only)
├── ground.py              # TerrainColumn, SoilLayer, materials
├── tools.py               # Tool system (Toolbar, Tool, ToolOption)
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
