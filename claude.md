# Kemet - Project Context for Claude

## Known Issues

### Active Bugs

1. **Stuttery movement** - Moving over simulation tile thresholds feels slightly slower than regular movement. Worse when camera also moves.
   - *Potential causes*: per-frame Surface allocations in water rendering, `pygame.transform.scale()` every frame
   - *Status*: Needs runtime profiling

### UI/UX Issues

2. **Navigation** - Hard to find the depot; needs a minimap
3. **UI proportions** - Information displays not in clean columns
4. **Dead space** - Map feels crowded; consider HUD overlay approach with floating windows
5. **No clock** - Hard to tell time of day

---

## Critical Architecture: Unified Layer System

With the surface, subterranean, and planned atmospheric layers now functional, we should unify the layer architecture to avoid technical debt. A unified abstract layer system should:

- Define all soil and environmental sub-layers in a single framework
- Allow shared rules with custom behavior per layer
- Use meta-group tags ("surface", "underground") as labels only, not containers
- Allow any layer to serve as the exposed top layer and render appropriately

### Progress

**Phase 1: Consolidate Existing - COMPLETE**
- Created `surface_state.py` with computed appearance system
- Removed `SubSquare.biome` - visuals now computed from terrain/water/organics
- Created unified water access helpers (`get_tile_total_water()`, etc.)
- `Tile.kind` retained for simulation properties (evap rates, capacity)

**Phase 2: Abstract Layer Interface** (if needed)
- Adapter pattern to wrap existing classes with unified interface

**Phase 3: Atmosphere Layer**
- Add humidity/wind following same layer pattern

### Appearance System (NEW)

Visual rendering is now computed from environmental factors in `surface_state.py`:

```python
appearance = compute_surface_appearance(subsquare, tile)
# Factors considered:
# - Exposed material (from terrain column)
# - Surface water amount
# - Organics layer depth
# Future: humidity, neighbors, structures
```

---

## Project Vision

Kemet is a terraforming simulation where:
- Surface water flows based on terrain slope, causing erosion
- Fertile topsoil is a resource to protect and build
- Wind and humidity affect evaporation
- Player builds structures to manage water and cultivate land

---

## Architecture Overview

### Three Simulation Layers

| Layer | Grid Resolution | Update Frequency | Contents |
|-------|-----------------|------------------|----------|
| **Atmosphere** | Region (4x4 tiles) | Every 10+ ticks | Humidity, wind, evaporation pressure |
| **Surface** | Sub-grid (3x3 per tile) | Every tick | Player, structures, surface water, erosion |
| **Subsurface** | Tile (current) | Every tick | Soil layers, water table, vertical seepage |

### Water Simulation Pipeline

Each tick runs these phases in order:
1. **Surface flow** - 8-neighbor flow between sub-squares based on elevation
2. **Surface seepage** - Water infiltrates topmost soil layer (permeability-based)
3. **Subsurface tick** - Wellspring output, vertical seepage, horizontal flow, capillary rise
4. **Evaporation** - Per-sub-square with biome and trench modifiers

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
- `elevation_offset: float` - Height relative to tile base
- `surface_water: int` - Water pooled on this sub-square
- `structure_id: Optional[int]` - Structure occupying this sub-square
- `has_trench: bool` - Reduces evaporation
- `terrain_override: Optional[TerrainColumn]` - Per-sub-square terrain modifications
- Visual appearance computed via `surface_state.compute_surface_appearance()`

**Coordinate system:**
- World sub-coords: `(tile_x * 3 + sub_x, tile_y * 3 + sub_y)`
- For 60x45 tile map -> 180x135 sub-square map
- Player position: sub-square coordinates

**Key Design Principle: Sub-squares are independent units**
- Each sub-square flows to all 8 neighbors (cardinal + diagonal)
- Tile boundaries are invisible to surface flow
- The 3x3 grouping is purely organizational

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

---

## Implementation Status

### Phase 1: Sub-Grid Foundation - COMPLETE
Player moves on 180x135 grid, interaction range highlights work, cursor targeting functional.

### Phase 2: Surface Water on Sub-Grid - COMPLETE
- Surface water stored per sub-square
- 8-directional flow based on elevation + water depth
- Surface-to-soil seepage implemented
- Elevation-weighted upward seepage (capillary rise, overflow)
- Water system reaches equilibrium with visible pooling near wellsprings

### Phase 2.5: Unified Layer System Phase 1 - COMPLETE
- Created `surface_state.py` with computed appearance system
- Removed stored `SubSquare.biome` - now computed from terrain/water state
- Visual appearance factors: exposed material, water amount, organics depth
- Unified water access helpers in `surface_state.py`

### Phase 3: Erosion System - PLANNED
Water and wind move surface material. Rivers carve channels.

### Phase 4: Atmosphere Layer - PLANNED
Regional humidity grid affecting evaporation rates.

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

---

## Water Balance (Current Tuning)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Evaporation (dune/flat/rock) | 1 unit/tick | Reduced from 9-12 |
| Evaporation (wadi) | 0 units/tick | Wadis retain water |
| Evaporation (salt) | 2 units/tick | Salt flats dry fastest |
| Primary wellspring | 40-60 units/tick | 4-6L/tick output |
| Secondary wellspring | 15-30 units/tick | 1.5-3L/tick output |
| Surface seepage rate | 15% | Infiltration to soil |
| Capillary rise rate | 5% | Slow upward movement |

System reaches equilibrium with ~2500 units surface water on a 20x20 map.

---

## File Structure

```
kemet/
├── config.py              # Constants including water rates
├── main.py                # GameState, tick orchestration
├── subgrid.py             # SubSquare, coordinate utils, terrain override
├── surface_state.py       # NEW: Computed appearance, unified water access
├── player.py              # Player state (sub-grid position)
├── camera.py              # Viewport transforms
├── mapgen.py              # Map generation, tile types (simulation props)
├── water.py               # WaterColumn (subsurface only)
├── ground.py              # TerrainColumn, SoilLayer, materials
├── simulation/
│   ├── surface.py         # Surface flow + seepage
│   └── subsurface.py      # Underground flow + evaporation
├── render/
│   ├── map.py             # Map + water visualization
│   ├── colors.py          # Color computation (uses surface_state)
│   └── hud.py             # HUD panels + soil profile
├── structures.py          # Cistern, condenser, planter
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
8. [ ] Erosion moves material based on water velocity
9. [ ] Atmosphere affects regional evaporation
