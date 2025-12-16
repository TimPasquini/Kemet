# Claude Work-in-Progress

Last updated: 2025-12-15

---

## Current Goals

### 1. Unified Layer System (Architecture)

Consolidate surface and subsurface systems into a unified layer framework.

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
- `compute_surface_appearance()` called per sub-square per frame (potential caching opportunity)

---

## Relevant Research

### Current Layer Architecture (Post-Phase 1)

```
Surface Layer (SubSquare)
├── elevation_offset: float
├── surface_water: int      <- CANONICAL surface water storage
├── terrain_override: Optional[TerrainColumn]
├── has_trench, structure_id
└── [Visual computed via surface_state.compute_surface_appearance()]

Subsurface Layer (TerrainColumn + WaterColumn)
├── 6 soil layers: BEDROCK → ORGANICS
├── Each layer: material + depth
└── WaterColumn.layer_water: Dict[SoilLayer, int]

Appearance System (NEW: surface_state.py)
├── compute_surface_appearance() - computes visual from factors
├── SurfaceAppearance - dataclass with type, color, pattern
└── Factors: exposed material, water state, organics depth
    (Future: humidity, neighbors, structures)
```

### Key Patterns

- `get_exposed_layer()` - Returns topmost layer with non-zero depth
- `ensure_terrain_override()` - Copy-on-write for per-sub-square terrain
- `get_subsquare_terrain()` - Falls back to tile terrain if no override
- `compute_surface_appearance()` - Derives visual state from factors

### Water Transfer Methods (All Working)

| Transfer | Function | Location |
|----------|----------|----------|
| Surface → Surface | `simulate_surface_flow()` | simulation/surface.py |
| Surface → Subsurface | `simulate_surface_seepage()` | simulation/surface.py |
| Subsurface → Surface | `distribute_upward_seepage()` | simulation/surface.py |
| Subsurface → Subsurface | `calculate_subsurface_flow()` | water.py |
| Vertical seepage | `simulate_vertical_seepage()` | water.py |
| Capillary rise | Returns from `simulate_vertical_seepage()` | water.py |

---

## Immediate Next Steps

1. **Playtest** - Verify visual appearance looks correct with new system
2. **Consider caching** - If performance is an issue, cache computed appearances
3. **Atmosphere Layer** - When ready to proceed with Phase 3

---

## File Quick Reference

| File | Key Contents |
|------|--------------|
| `surface_state.py` | **NEW**: `SurfaceAppearance`, `compute_surface_appearance()`, water helpers |
| `subgrid.py` | `SubSquare`, `ensure_terrain_override()`, `get_subsquare_terrain()` |
| `ground.py` | `TerrainColumn`, `SoilLayer`, `MATERIAL_LIBRARY`, `get_exposed_layer()` |
| `water.py` | `WaterColumn`, `simulate_vertical_seepage()` |
| `render/colors.py` | `color_for_subsquare()` - uses computed appearance |
| `simulation/surface.py` | `simulate_surface_flow()`, `simulate_surface_seepage()` |
| `simulation/subsurface.py` | `simulate_subsurface_tick()`, `apply_tile_evaporation()` |
| `mapgen.py` | `Tile`, `TILE_TYPES` (simulation props), wellspring generation |
| `config.py` | Water rate constants |
