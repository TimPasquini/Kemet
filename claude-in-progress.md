# Claude Work-in-Progress

Last updated: 2025-12-16

---

## Recently Completed

### Render Caching System
- ✅ Static terrain pre-rendered to background surface
- ✅ Dirty subsquare tracking via coordinate tuples (pygame-agnostic)
- ✅ Background regenerated when terrain changes
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

**Phase 2 tasks (if needed):**
- Abstract layer interface with adapter pattern
- Consider if TerrainColumn/WaterColumn need unified interface

**Phase 3: Atmosphere Layer (future)**
- Add humidity/wind following same layer pattern

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
2. update_dirty_background() - Regenerate if dirty_subsquares non-empty
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
| `surface_state.py` | `SurfaceAppearance`, `compute_surface_appearance()`, water helpers |
| `subgrid.py` | `SubSquare`, `ensure_terrain_override()`, `get_subsquare_terrain()` |
| `structures.py` | `Structure` ABC, `Condenser`, `Cistern`, `Planter` subclasses |
| `render/map.py` | `render_static_background()`, `render_map_viewport()` |
| `pygame_runner.py` | `update_dirty_background()`, background surface management |
