# Kemet - Project Context for Claude

## Project Vision

Kemet is a terraforming simulation where:
- **Erosion sculpts terrain**: Starting from abundant material, water and wind carve hills, valleys, rivers, lakes
- **Player moves dirt, doesn't create/destroy it**: Wheelbarrow → cart → bulldozer progression
- **Conservation of mass/water**: Core mechanic - nothing vanishes, everything goes somewhere
- **Topology matters**: Elevation affects movement and gameplay, not just visuals
- **WFC for appearance**: Simulations provide constraints for wave function collapse to determine biome visuals

### Design Philosophy: Systems Respond Naturally

The player can place anything anywhere, but natural systems respond realistically:
- Pile organics in a stream → they wash downstream and deposit elsewhere
- Stack sand on an exposed hilltop → wind blows it away
- Block water flow → it pools and finds another path

This creates emergent gameplay where understanding the systems lets you work with nature rather than against it.

---

## Known Issues

### Performance (Under Investigation)

**Symptom**: Stuttery movement, inconsistent tick rhythm even when standing still.

**Current mitigation**: Staggered simulation schedule spreads load across ticks.

**Remaining suspects**:
- Rendering overhead (not yet profiled with pygame)
- GC pauses
- Something else outside simulation

**Unimplemented Potential Optimizations**
  1. Spatial partitioning - Only process tiles with water above a threshold
  2. Delta-based updates - Track which tiles changed and only recalculate neighbors
  3. Chunked processing - Spread subsurface work across multiple frames instead of one spike
  4. Use numpy arrays - Replace nested Python loops with vectorized operations

### UI/UX Issues

1. **Navigation** - Hard to find the depot; needs a minimap
2. **UI proportions** - Information displays not in clean columns
3. **Dead space** - Map feels crowded; consider HUD overlay with floating windows
4. **No clock** - Hard to tell time of day

### Gameplay Issues

1. **Topology doesn't feel meaningful** - Player walks freely regardless of elevation
2. **Layers too thin** - Current ~1m of soil erodes to bedrock too quickly
3. **No pre-simulation** - Map shows raw generation, not eroded terrain

---

## Architecture Overview

### Three Simulation Layers

| Layer | Grid Resolution | Update Frequency | Contents |
|-------|-----------------|------------------|----------|
| **Atmosphere** | Region (4x4 tiles) | Every tick | Humidity, wind, evaporation pressure |
| **Surface** | Sub-grid (3x3 per tile) | Every 2 ticks | Player, structures, surface water, erosion |
| **Subsurface** | Tile | Every 4 ticks | Soil layers, water table, vertical seepage |

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
- `surface_water: int` - Water pooled on this sub-square
- `structure_id: Optional[int]` - Structure occupying this sub-square
- `has_trench: bool` - Reduces evaporation
- `terrain_override: Optional[TerrainColumn]` - Per-sub-square terrain modifications
- `water_passage: float` - Daily accumulator for erosion calculations
- `wind_exposure: float` - Daily accumulator for wind erosion

**Coordinate system:**
- World sub-coords: `(tile_x * 3 + sub_x, tile_y * 3 + sub_y)`
- For 60x45 tile map → 180x135 sub-square map
- Player position: sub-square coordinates

---

## Future Architecture: Geological Erosion

### Two-Phase Terrain Model (Planned)

**Phase 1: Proto-Terrain (Pre-Game)**
- Start with ~100m of bulk material
- Simplified single-layer model with hardness variation
- Run 500-2000 erosion cycles during loading
- Water from wellsprings carves terrain reductively

**Phase 2: Game Terrain (Converted at Start)**
- Convert eroded proto-terrain to detailed soil layers
- Layer distribution based on remaining material depth
- Thin material = exposed bedrock; thick = full soil profile

### Key Concepts

- **Game floor**: True immutable bottom beneath erodible bedrock
- **Hardness variation**: Spatial noise creates ridges (hard) and valleys (soft)
- **Sediment return**: Material eroded off edges returns via dust storms
- **Open edges**: Water/material flows off map freely during pre-game erosion

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

### Phase 5: Erosion System - IN PROGRESS
- Overnight erosion using accumulated daily pressures
- Water passage and wind exposure tracking
- Real-time erosion moved to overnight processing

### Phase 6: Geological Pre-Simulation - PLANNED
- Proto-terrain with ~100m bulk material
- Pre-game erosion cycles
- Conversion to detailed layers at game start

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
- `simulate_surface_flow()` - Horizontal flow between sub-squares
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
├── config.py              # Constants including water rates, tick intervals
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
├── simulation/
│   ├── surface.py         # Surface flow + seepage (with edge runoff)
│   ├── subsurface.py      # Underground flow + evaporation
│   └── erosion.py         # Overnight erosion, wind exposure accumulation
├── render/
│   ├── map.py             # Map + water visualization (cached surfaces)
│   ├── colors.py          # Color computation (uses surface_state)
│   └── hud.py             # HUD panels + soil profile
├── structures.py          # Structure ABC + Cistern, Condenser, Planter
└── ui_state.py            # UI state + cursor tracking
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
