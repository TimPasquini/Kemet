# Claude Work-in-Progress

Last updated: 2025-12-15

---

## Current Goals

### 1. Unified Layer System (Architecture)

Consolidate surface and subsurface systems into a unified layer framework.

**Phase 1 tasks:**
- Remove `SubSquare.biome` redundancy - derive visual from exposed material's `display_color`
- Create unified water access helper (surface from SubSquare + subsurface from WaterColumn)

**Key patterns to preserve:**
- `get_exposed_layer()` - Returns topmost layer with non-zero depth
- `ensure_terrain_override()` - Copy-on-write for per-sub-square terrain
- `get_subsquare_terrain()` - Falls back to tile terrain if no override

### 2. Performance Investigation (Low Priority)

Stuttery movement at tile boundaries needs runtime profiling.

**Suspected causes:**
- `pygame.Surface()` allocations per sub-square in `render_subgrid_water()`
- `pygame.transform.scale()` called every frame
- Possible: collision checks triggering extra work at tile boundaries

---

## Relevant Research

### Current Layer Architecture

```
Surface Layer (SubSquare)
├── biome: str              <- REDUNDANT, should derive from material
├── elevation_offset: float
├── surface_water: int      <- CANONICAL surface water storage
├── terrain_override: Optional[TerrainColumn]
└── has_trench, structure_id

Subsurface Layer (TerrainColumn + WaterColumn)
├── 6 soil layers: BEDROCK → ORGANICS
├── Each layer: material + depth
└── WaterColumn.layer_water: Dict[SoilLayer, int]
```

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

1. **Playtest the water fixes** - Verify visible pooling near wellsprings in actual gameplay
2. **If proceeding with layer unification:**
   - Start with `SubSquare.biome` removal (low risk, high clarity)
   - Map exposed material → visual color in `color_for_subsquare()`
3. **If investigating stutter:**
   - Add frame timing instrumentation to identify slow frames
   - Profile Surface allocation counts per frame

---

## File Quick Reference

| File | Key Contents |
|------|--------------|
| `subgrid.py` | `SubSquare`, `ensure_terrain_override()`, `get_subsquare_terrain()` |
| `ground.py` | `TerrainColumn`, `SoilLayer`, `MATERIAL_LIBRARY`, `get_exposed_layer()` |
| `water.py` | `WaterColumn`, `simulate_vertical_seepage()` |
| `simulation/surface.py` | `simulate_surface_flow()`, `simulate_surface_seepage()` |
| `simulation/subsurface.py` | `simulate_subsurface_tick()`, `apply_tile_evaporation()` |
| `mapgen.py` | `TILE_TYPES` (evap rates), `_generate_wellsprings()` |
| `config.py` | Water rate constants |
