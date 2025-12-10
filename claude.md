# Kemet - Project Context for Claude

## ⚠️ URGENT - Known Bugs (Playtest Findings)

These issues need immediate attention:

1. **Soil profile meter** - Still doesn't show surface/sub-square profile, only simulation tile
2. **Shovel actions operate at sim-tile scale** - dig/raise/lower use cursor target but modify entire simulation tile, not individual sub-squares
3. **Structure builds at sim-tile scale** - Uses cursor selection but builds on simulation tile, not surface layer
4. **Trench tool mismatch** - Uses sub-square selection UI but builds at simulation tile scale

**Root cause:** Actions target cursor but game logic still operates on `Tile` objects (simulation scale), not `SubSquare` objects (surface scale). Need to refactor terrain modification and structure placement to work at sub-square resolution.

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
| **Subsurface** | Tile (current) | Every 4-8 ticks | Soil layers, water table, vertical seepage |

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
- `elevation_offset: float` - Height relative to tile base (enables slopes)
- `surface_water: int` - Water pooled on this sub-square
- `surface_material: str` - What's exposed (soil type, rock, structure foundation)
- `structure_id: Optional[int]` - Reference to structure occupying this sub-square

**Coordinate system:**
- World sub-coords: `(tile_x * 3 + sub_x, tile_y * 3 + sub_y)`
- For 60x45 tile map -> 180x135 sub-square map
- Player position: sub-square coordinates

**Key Design Principle: Sub-squares are independent units**
- Each sub-square flows to all 8 neighbors (cardinal + diagonal)
- Tile boundaries are invisible to surface flow - water crosses freely
- The 3x3 grouping is purely organizational (storage + relation to subsurface)
- No artificial barriers at tile edges

---

## Confirmed Design Decisions

- [x] Sub-grid size: **3x3** per tile
- [x] Player movement: **Sub-grid level**
- [x] Range calculation: **Chebyshev distance** (square range)
- [x] Actions at range: **Yes** (act on target without moving)
- [x] Surface water: **Sub-grid level** (for erosion support)
- [x] Surface flow: **8-neighbor** (cardinal + diagonal) for natural spreading
- [x] Sub-squares: **Independent units** - tile boundaries invisible to flow
- [x] Upward seepage: **Elevation-weighted** distribution (lowest gets most, but not exclusive)

---

## Implementation Roadmap

### Phase 1: Sub-Grid Foundation (COMPLETE)
**Goal:** Sub-grid coordinates, player movement, building placement, rendering

**New files:**
- `subgrid.py` - SubSquare dataclass, coordinate conversion utilities

**Modified files:**
- `config.py` - Add `SUBGRID_SIZE = 3`, update `TILE_SIZE` semantics
- `player.py` - Player position in sub-coords, movement on sub-grid
- `camera.py` - Update transforms for sub-grid
- `render/map.py` - Render at sub-grid resolution
- `pygame_runner.py` - Mouse -> sub-coord conversion

**Deliverable:** Player moves on 180x135 grid, interaction range highlights work.

---

### Phase 2: Surface Water on Sub-Grid (COMPLETE)
**Goal:** Real sub-grid surface water flow

**New files:**
- `simulation/__init__.py` - Simulation module exports
- `simulation/surface.py` - Sub-grid surface water flow (8-neighbor)
- `simulation/subsurface.py` - Tile-level underground flow + evaporation

**Modified files:**
- `main.py` - Split `simulate_tick()` into surface and subsurface phases
- `mapgen.py` - Distribute initial surface water to sub-squares
- `structures.py` - Update cistern/condenser/planter to use sub-grid water
- `render/map.py` - Add sub-grid water visualization overlay

**Key features:**
- Surface water stored per sub-square (9 per tile)
- 8-directional flow based on elevation + water depth
- Elevation-weighted upward seepage (lowest sub-squares get most)
- Semi-transparent blue water visualization at sub-grid resolution
- Structures interact with sub-grid water (collect/distribute proportionally)

**Deliverable:** Water visibly pools in low sub-squares, flows along slopes, emerges naturally from underground.

---

### Phase 3: Erosion System (PLANNED)
**Goal:** Water and wind move surface material

**New files:**
- `simulation/erosion.py` - Erosion calculations

**Model:**
- Water velocity (flow_in - flow_out) determines erosion rate
- Material erodibility varies by type
- Eroded material deposited downstream

**Deliverable:** Rivers carve channels, wind moves loose sand, fertile soil can wash away.

---

### Phase 4: Atmosphere Layer (PLANNED)
**Goal:** Regional humidity and evaporation

**New files:**
- `simulation/atmosphere.py` - Humidity grid, evaporation calculations

**Model:**
- Divide map into 15x11 regions (4x4 tiles each)
- Each region tracks humidity (0-100)
- Evaporation rate varies by humidity
- Water bodies increase local humidity
- Wind moves humidity between regions

**Deliverable:** Dry regions evaporate faster, water bodies create local humidity.

---

## File Structure (Target)

```
kemet/
├── config.py              # Constants including SUBGRID_SIZE
├── main.py                # GameState, tick orchestration
├── subgrid.py             # SubSquare, coordinate utils
├── player.py              # Player state (sub-grid position)
├── camera.py              # Viewport transforms (sub-grid aware)
├── mapgen.py              # Map generation (creates subgrid)
├── simulation/            # Simulation modules
│   ├── __init__.py
│   ├── surface.py         # Sub-grid surface water flow
│   ├── subsurface.py      # Tile-level underground water
│   ├── erosion.py         # Surface material movement
│   └── atmosphere.py      # Regional humidity
├── render/
│   ├── map.py             # Map + subgrid rendering
│   └── toolbar.py         # UI rendering
├── structures.py          # Building definitions
├── tools.py               # Tool definitions
└── ui_state.py            # UI state + cursor tracking
```

---

## Interaction Range System

### Config
```python
INTERACTION_RANGE = 2  # sub-squares from player
SUBGRID_SIZE = 3
```

### UI State
```python
hovered_subsquare: Optional[Tuple[int, int]]  # Sub-grid coords under cursor
target_subsquare: Optional[Tuple[int, int]]   # Clamped to interaction range
```

### Rendering
- **Range indicator:** Subtle highlight on all sub-squares within range
- **Target highlight:** Bright outline on target sub-square
- **Building preview:** Show full footprint (may span multiple sub-squares)

### Tool Colors
- Build: Blue (valid) / Red (invalid)
- Shovel/terrain: Yellow
- Bucket/water: Cyan
- Survey: Green

---

## Key Implementation Notes

### Coordinate Conversion
```python
def tile_to_subgrid(tile_x, tile_y):
    return (tile_x * SUBGRID_SIZE, tile_y * SUBGRID_SIZE)

def subgrid_to_tile(sub_x, sub_y):
    return (sub_x // SUBGRID_SIZE, sub_y // SUBGRID_SIZE)

def chebyshev_distance(p1, p2):
    return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))
```

### 8-Neighbor Flow
```python
NEIGHBORS_8 = [(-1,-1), (0,-1), (1,-1),
               (-1, 0),         (1, 0),
               (-1, 1), (0, 1), (1, 1)]
```

### Upward Seepage Distribution
```python
def distribute_upward_seepage(tile, water_amount):
    # Weight by inverse elevation - lower sub-squares get more
    weight = 1.0 / (sub.elevation_offset + 0.1)
```

---

## Known Issues

- **Wall sliding implemented** - Axis-separated collision now allows sliding along obstacles
- **Building collision** - Player blocked by structures
- **Left-click triggers tools** - Click in map area uses selected tool at cursor

---

## Future Work (Not Yet Implemented)

### Actions at Range
Currently actions (dig, build, pour, etc.) happen at the player's tile. The interaction range system is visual-only. Need to:
- Pass `target_subsquare` to action handlers
- Convert target sub-square to tile for tile-level actions
- Update `handle_command()` to use target position instead of player position

### Tool Previews
- **Shovel:** Show elevation change preview at target
- **Pour:** Show water spread preview (which sub-squares will receive water)
- **Build:** Show structure footprint preview (may span multiple sub-squares)

---

## Testing Checkpoints

1. Player renders at sub-grid position, moves in smaller increments
2. Sub-grid renders, can see tile subdivisions
3. Cursor highlights target sub-square within range
4. Actions work at range (dig/build on target tile) - **NOT YET IMPLEMENTED**
5. Subsurface simulation runs at reduced frequency
6. Surface water flows at sub-grid level, pools in low spots
