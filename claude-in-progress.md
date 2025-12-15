# Claude Work-in-Progress

## Session Date: 2025-12-14

This file tracks current work to preserve context across sessions.

---

## Playtest Feedback (NEEDS ATTENTION)

**Observation:** Human playtesting shows almost no surface water anywhere on the map.

While this may be appropriate for a desert starting state, we need to ensure:

1. **Wellsprings are large enough** to create sustainable surface flow somewhere on the map
2. **Water system is working correctly** - capillary rise, overflow, and surface flow should be producing visible results
3. **Initial water distribution** may need tuning in `mapgen.py`:
   - Primary wellspring: 80 units surface + 100 units regolith
   - Secondary wellsprings: 20 units surface + 30 units regolith
   - Wadis: 5-30 units surface water

**Potential issues to investigate:**
- Evaporation may be too aggressive relative to wellspring output
- Surface-to-soil seepage (downward) is not yet implemented - water may be seeping down faster than it flows
- Wellspring output rates may need increase (`wellspring_output` currently 8-12 for primary, 2-6 for secondary)

**Priority:** Verify water systems are functional before tuning. Players should see *some* visible water pooling near wellsprings.

---

## Completed Work (Session 2025-12-14)

All items below are DONE and committed:

### Bug Fixes
- [x] HUD water display - now uses `get_tile_surface_water(tile)`
- [x] Soil profile meter - uses `get_subsquare_terrain()`
- [x] Shovel actions - work at sub-square level via `ensure_terrain_override()`
- [x] Structure builds - work at sub-square level
- [x] Trench tool - works at sub-square level

### Dead Code Removal
- [x] Removed `WaterColumn.surface_water` field
- [x] Removed `WaterColumn.total_water()` method
- [x] Removed `calculate_surface_flow()` function
- [x] Removed `apply_flows()` function

### Bug Discovered and Fixed
- [x] Capillary rise was broken - water was being added to dead `WaterColumn.surface_water` field
- [x] Now returns amount and caller distributes to sub-squares via `distribute_upward_seepage()`

### Architecture Documentation
- [x] Created unified layer system plan (3 phases)
- [x] Documented existing patterns and migration strategy

---

## Unified Layer System Plan (Reference)

### Phase 1: Consolidate Existing (RECOMMENDED FIRST)

1. **Remove `SubSquare.biome`** - Derive from exposed material
2. **Add surface-to-soil seepage** - Currently missing per-sub-square downward seepage
3. **Unify water access patterns**

### Phase 2: Abstract Layer Interface (IF NEEDED)

Use adapter pattern to wrap existing classes with unified interface.

### Phase 3: Atmosphere Layer (FUTURE)

Add humidity/wind following same layer pattern.

---

## File Reference Map

| File | Purpose | Key Functions |
|------|---------|---------------|
| `water.py` | Subsurface water only now | `WaterColumn`, `simulate_vertical_seepage()` |
| `simulation/surface.py` | Surface water flow | `simulate_surface_flow()`, `get_tile_surface_water()`, `distribute_upward_seepage()` |
| `simulation/subsurface.py` | Underground water + capillary | `simulate_subsurface_tick()` |
| `mapgen.py` | Map generation | `_distribute_water_to_subgrid()`, `_get_tile_total_water()` |
| `subgrid.py` | Sub-square system | `ensure_terrain_override()`, `get_subsquare_terrain()` |

---

## Next Priority

1. **Investigate surface water scarcity** - Why is there almost no visible surface water?
2. **Add surface-to-soil seepage** - Water on surface should seep into topmost soil layer
3. **Tune water balance** - Ensure wellsprings produce enough to overcome evaporation
