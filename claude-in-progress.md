# Claude Work-in-Progress

Last updated: 2025-12-16

---

## Recently Completed

### Phase 2: Atmosphere Layer (2025-12-16)
- ✅ Created `atmosphere.py` with `AtmosphereRegion` and `AtmosphereLayer`
  - Regions cover 4x4 tiles with humidity, wind direction/speed
  - Humidity affects evaporation rate (high humidity = less evap)
  - Wind speed increases evaporation
- ✅ Integrated atmosphere into simulation pipeline
  - `atmosphere` field on GameState, initialized in `build_initial_state()`
  - `apply_tile_evaporation()` uses `atmosphere.get_evaporation_modifier()`
  - `simulate_atmosphere_tick()` evolves humidity/wind over time
- ✅ Fixed structure collision detection
  - Changed from tile-level to subsquare-level collision
  - Structures only block the specific subsquare they occupy

### Phase 1 Technical Debt (2025-12-16)
- ✅ Extracted `remove_water_proportionally()` to `simulation/surface.py`
  - Eliminated duplicate water distribution logic in main.py and structures.py
- ✅ Added `_tick_timer: float` field to GameState dataclass
  - Removed dynamic attribute usage with getattr() in pygame_runner.py
- ✅ Implemented true dirty-rect updates in `update_dirty_background()`
  - Now uses `redraw_background_rect()` per subsquare instead of full regeneration
- ✅ Changed trench rendering from "~" text to visible 2px border

### Render Caching System
- ✅ Static terrain pre-rendered to background surface
- ✅ Dirty subsquare tracking via coordinate tuples (pygame-agnostic)
- ✅ True dirty-rect redraws (only changed subsquares)
- ✅ Elevation-based brightness applied correctly to cached terrain

### Structure Refactoring
- ✅ `Structure` is now an abstract base class
- ✅ `Condenser`, `Cistern`, `Planter` are concrete subclasses
- ✅ Each structure implements `tick()`, `get_survey_string()`, `get_status_summary()`
- ✅ Polymorphic dispatch in `tick_structures()` and status display

---

## Current Goals

### 1. Unified Layer System (Architecture)

**Phase 1: COMPLETE**
- ✅ Created `surface_state.py` with computed appearance system
- ✅ Removed `SubSquare.biome` - now computed from terrain/water state
- ✅ Created unified water access helpers

**Phase 2: Atmosphere Layer - COMPLETE**
- ✅ Created `atmosphere.py` with regional humidity/wind
- ✅ Integrated into evaporation calculation
- ✅ Atmosphere evolves over time based on heat

**Phase 3: Erosion System (next)**
- Water velocity moves surface material
- Wind affects exposed terrain

### 2. Performance Investigation (Low Priority)

Stuttery movement at tile boundaries needs runtime profiling.

**Suspected causes:**
- `pygame.Surface()` allocations per sub-square in `render_subgrid_water()`
- `pygame.transform.scale()` called every frame

Note: Static terrain is now cached. Appearance computation is cached per-subsquare.

---

## Architecture Notes

### Render Pipeline

```
1. render_static_background() - One-time terrain render (cached)
2. update_dirty_background() - Redraw only dirty subsquares via redraw_background_rect()
3. render_map_viewport() - Blit background + draw dynamic elements
4. render_subgrid_water() - Semi-transparent water overlay
5. render_player(), render_night_overlay() - Top-level overlays
```

### Key Design: Pygame Isolation

Pygame-specific code stays in `pygame_runner.py` and `render/`.
`main.py` and `GameState` use pygame-agnostic types:
- `dirty_subsquares: List[Point]` not `List[pygame.Rect]`
- Background surface stored in pygame_runner.py, not GameState

---

## File Quick Reference

| File | Key Contents |
|------|--------------|
| `atmosphere.py` | `AtmosphereLayer`, `AtmosphereRegion`, `simulate_atmosphere_tick()` |
| `surface_state.py` | `SurfaceAppearance`, `compute_surface_appearance()`, water helpers |
| `simulation/surface.py` | `simulate_surface_flow()`, `remove_water_proportionally()` |
| `simulation/subsurface.py` | `apply_tile_evaporation()` (uses atmosphere humidity) |
| `subgrid.py` | `SubSquare`, `ensure_terrain_override()`, `get_subsquare_terrain()` |
| `structures.py` | `Structure` ABC, `Condenser`, `Cistern`, `Planter` subclasses |
| `render/map.py` | `render_static_background()`, `redraw_background_rect()` |
| `pygame_runner.py` | `update_dirty_background()`, subsquare-level collision |
