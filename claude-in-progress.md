# Claude Work-in-Progress

## Session Date: 2025-12-14

This file tracks current work to preserve context across sessions.

---

## Water System Overhaul (COMPLETED)

### Problem Identified
Human playtesting showed almost no surface water anywhere. Audit revealed:
- **Evaporation was too high**: 9-14 units/tick per sub-square vs 2-3 units average water
- **Wellspring output too low**: 10-15 units/tick total vs 81+ units/tick evaporation
- **Missing surface seepage**: Water couldn't infiltrate soil, just evaporated

### Fixes Applied
1. **Reduced evaporation rates** (`mapgen.py` TILE_TYPES):
   - dune: 12→1, flat: 9→1, wadi: 5→0, rock: 6→1, salt: 14→2

2. **Increased wellspring output** (`mapgen.py` _generate_wellsprings):
   - Primary: 8-12 → 40-60 units/tick, initial 200 surface + 200 subsurface
   - Secondary: 2-6 → 15-30 units/tick, initial 80 surface + 100 subsurface

3. **Added surface seepage** (`simulation/surface.py` simulate_surface_seepage):
   - New function: surface water seeps into topmost soil layer
   - Rate controlled by SURFACE_SEEPAGE_RATE (15%) and material permeability
   - Called between surface flow and subsurface tick

### Results (100-tick simulation)
- Surface water stabilized at ~2500 units (was disappearing completely before)
- ~750 wet sub-squares maintained (21% of map)
- Wellspring areas pool 17-44L in 3x3 surrounding tiles
- Water system now reaches equilibrium instead of draining to zero

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
