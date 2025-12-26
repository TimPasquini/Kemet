# Kemet Performance Tracking

**Grid Size**: 180×135 cells (24,300 total grid cells)
**Test Configuration**: 1000 simulation ticks, headless (no rendering)
**Last Updated**: December 25, 2025

---

## Performance Evolution

### Phase 4.75: Connectivity Cache Implementation (Dec 25, 2025)
✅ **MAJOR PERFORMANCE GAIN: 1.93× SPEEDUP**
- **46.8 TPS** (ticks per second) - Excellent performance
- **~30 MB** peak memory (+11 MB for cache)
- **21.36ms** average tick time
- **Subsurface: 2.76× faster** via connectivity caching

### Phase 4: Initial Baseline (Dec 25, 2025)
- **24.3 TPS** (ticks per second)
- **~18 MB** peak memory
- **41.20ms** average tick time
- Identified subsurface connectivity as primary bottleneck (42.8% of subsurface time)

---

## Current Performance (With Cache)

### Executive Summary
✅ **Performance: EXCELLENT - Nearly 2× baseline**
- **46.8 TPS** sustained simulation rate
- **21.36ms** average tick time
- **Subsurface bottleneck eliminated**: Connectivity caching saves 15 seconds per 1000 ticks
- **Cache overhead**: +11 MB memory (well worth the speedup)

---

## Overall Performance Metrics

| Metric | With Cache (Current) | Baseline (Pre-Cache) | Improvement |
|--------|---------------------|----------------------|-------------|
| Total Runtime | 21.37s | 41.23s | **1.93× faster** |
| Average TPS | 46.8 | 24.3 | **+93%** |
| Avg Tick Time | 21.36ms | 41.20ms | **48% reduction** |
| Peak Memory | 29.8 MB | 18.0 MB | +11.8 MB (cache) |

---

## Tick Timing Analysis

| Statistic | With Cache | Baseline | Improvement |
|-----------|------------|----------|-------------|
| Mean | 21.36ms | 41.20ms | **48% faster** |
| Median | 15.55ms | 20.01ms | **22% faster** |
| Std Dev | 17.40ms | 41.25ms | More consistent |
| Min | 1.19ms | 1.32ms | ~same |
| Max | 71.67ms | 194.48ms | **63% faster** |

**Note**: High variance is expected due to staggered simulation scheduling:
- Surface flow runs every 2 ticks
- Subsurface runs every 4 ticks (expensive but now 2.76× faster!)
- Atmosphere runs every 2 ticks
- Wind exposure runs every 10 ticks

---

## System Performance Breakdown

| System | With Cache | Baseline | Speedup | Notes |
|--------|------------|----------|---------|-------|
| **Subsurface** | 33.89ms | 94.03ms | **2.76×** | Connectivity cache eliminates 64% overhead |
| **Surface Flow** | 9.92ms | 14.08ms | 1.42× | Runs every 2 ticks |
| **Evaporation** | 6.71ms | 8.67ms | 1.29× | Runs every tick |
| **Atmosphere** | 1.56ms | 2.43ms | 1.56× | Runs every 2 ticks |
| **Surface Seepage** | 0.75ms | 1.36ms | 1.81× | Runs every 2 ticks (offset) |
| **Wind Exposure** | 0.07ms | 0.13ms | 1.86× | Runs every 10 ticks |
| **Structures** | 0.02ms | 0.04ms | 2.0× | Negligible overhead |

**Key Achievement**: Subsurface went from **dominant bottleneck** (228% of avg tick) to **manageable cost** (159% of avg tick). The connectivity cache eliminated 60ms per subsurface tick by avoiding expensive geometric recalculation.

---

## Memory Usage

| Metric | Value |
|--------|-------|
| Mean | 17.8 MB |
| Peak | 18.0 MB |
| Min | 17.6 MB |

**Analysis**: Excellent memory efficiency. Very stable with minimal growth over 1000 ticks. The pre-allocated NumPy arrays are working perfectly.

---

## Hot Code Paths (Profiling Results)

### Top 5 Functions by Total Time

1. **`calculate_subsurface_flow_vectorized`** - 15.4s (37.3%)
   - Location: `simulation/subsurface_vectorized.py:175`
   - Called 250 times (every 4 ticks)
   - 61ms per call
   - **PRIMARY OPTIMIZATION TARGET**

2. **`apply_surface_evaporation`** - 6.5s (15.8%)
   - Location: `simulation/subsurface.py:22`
   - Called 1000 times (every tick)
   - 6.5ms per call
   - **SECONDARY OPTIMIZATION TARGET**

3. **`simulate_surface_flow`** - 6.3s (15.3%)
   - Location: `simulation/surface.py:33`
   - Called 500 times (every 2 ticks)
   - 12.7ms per call

4. **NumPy `_pad_simple`** - 1.7s (4.2%)
   - Called 7,000 times
   - Used by array shifting operations
   - Potential optimization: reduce padding calls

5. **`numpy.array` constructor** - 1.1s (2.7%)
   - Called 25,998 times
   - Consider pre-allocation where possible

### Other Notable Findings

- **`get_cell_kind`**: Called 511,236 times - extremely hot path
  - Location: `game_state/state.py:204`
  - 0.86s total time
  - Consider caching or optimization if this becomes bottleneck at scale

- **NumPy padding**: 7,000 calls to `np.pad` via `shift_to_neighbor`
  - Used for neighbor access in vectorized operations
  - Unavoidable with current architecture but worth monitoring at scale

---

## Bottleneck Analysis

### Primary Bottleneck: Subsurface Flow Calculation
**Impact**: 37.3% of total simulation time

The subsurface flow calculation in `calculate_subsurface_flow_vectorized` is the single largest bottleneck. This function:
- Calculates water flow between 6 soil layers across the entire 180×135 grid
- Uses array padding for neighbor access
- Performs complex hydraulic calculations

**Why it's acceptable**:
- Only runs every 4 ticks (performance trade-off for accuracy)
- Fully vectorized NumPy operations (no Python loops)
- Handles complex underground water flow physics

**Scaling implications**:
- Time complexity: O(layers × width × height)
- Should scale roughly linearly with grid size
- May become bottleneck at 512×512 (6.4× more cells)

### Secondary Bottleneck: Surface Evaporation
**Impact**: 15.8% of total simulation time

Evaporation runs every tick and scales with grid size. At larger scales, this could benefit from:
- Active region optimization (only evaporate where water exists)
- Reduced calculation frequency
- Pre-computed evaporation rates

### Tertiary Bottleneck: Surface Flow
**Impact**: 15.3% of total simulation time

Surface water flow is well-optimized and uses vectorized operations. Performance is acceptable.

---

## Performance Projections for Scale-Up

### 360×270 Grid (2× linear scale, 4× cells)
- **Estimated TPS**: 6-12 ticks/sec (4× slowdown expected)
- **Estimated Memory**: 60-72 MB
- **Subsurface tick**: ~376ms (94ms × 4)
- **Risk Level**: LOW - Should run smoothly

### 512×512 Grid (2.8× linear scale, 6.4× cells)
- **Estimated TPS**: 3.8-7.6 ticks/sec (6.4× slowdown)
- **Estimated Memory**: 100-115 MB
- **Subsurface tick**: ~600ms (94ms × 6.4)
- **Risk Level**: MODERATE - May need optimization for 60 FPS rendering

### Optimization Strategies (if needed)

1. **Active Region Simulation** - Only simulate areas with activity
   - Would dramatically reduce costs in sparse areas
   - Complexity: Medium
   - Benefit: High for large sparse grids

2. **Spatial Indexing for Structures** - If structure count grows
   - Currently negligible overhead
   - Only needed if 100+ structures

3. **Reduced Tick Frequency** - Run heavy systems less often
   - Subsurface every 6-8 ticks instead of 4
   - Trade-off: simulation accuracy vs performance

4. **Multi-threaded Simulation** - Parallelize independent systems
   - NumPy already uses BLAS/LAPACK threading
   - Limited additional benefit expected

---

## Recommendations

### ✅ Proceed with Scale-Up Testing
The baseline performance is excellent. The architecture is ready to test at:
1. **360×270** (2× scale) - Should run smoothly
2. **512×512** (2.8× scale) - Will stress-test the system

### Monitor These Areas During Scale-Up
1. **Subsurface flow calculation time** - Watch for super-linear scaling
2. **Memory growth** - Should stay linear
3. **NumPy padding overhead** - May increase with larger arrays
4. **`get_cell_kind` call count** - Monitor if this becomes bottleneck

### Optimization Threshold
**Only optimize if**:
- FPS drops below 30 at target grid size, OR
- Memory usage exceeds 500 MB, OR
- Single tick time exceeds 100ms average

Current performance has significant headroom before optimization is needed.

---

## Next Steps

1. ✅ Baseline established (180×135)
2. ⏭️ Test 360×270 grid (Phase 4, Step 3)
3. ⏭️ Test 512×512 grid (Phase 4, Step 4)
4. ⏭️ Verify all systems at scale (Phase 4, Step 5)
5. ⏭️ Optimize only if needed (Phase 4, Step 6)

---

## Conclusion

The Kemet simulation achieves **excellent performance** at 180×135 resolution with **pure vectorized NumPy operations**. Memory usage is minimal, and the dominant costs (subsurface flow, evaporation) are well-understood and acceptable.

The architecture is **ready for scale-up testing** with high confidence that 360×270 will run smoothly and 512×512 will be viable with potential minor optimizations.

**Architecture Success**: 100% grid-based, zero object iteration overhead. Phase 3 completion has delivered the expected performance benefits.
