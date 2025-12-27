# Kemet Performance Benchmark History

This document tracks rendering and simulation performance benchmarks over time.

## Benchmark Format

Each entry includes:
- Date and phase context
- Test configuration (grid size, frames tested, zoom levels)
- Key performance metrics
- Component breakdowns
- Notable optimizations applied

---

## December 27, 2025 - Phase 4.75 Complete

**Context**: Post-critical bug fixes including adaptive resolution water rendering

**Test Configuration**:
- Grid size: 180×135 cells
- Frames tested: 600 frames across 6 zoom levels
- Zoom levels: 0.25×, 0.5×, 1.0×, 1.5×, 2.0×, 3.0×
- Test type: Full rendering benchmark with zoom testing

**Overall Performance**:
- **Average FPS**: 285.8 FPS
- **Mean frame time**: 3.50ms
- **Median frame time**: 3.47ms
- **Min frame time**: 2.89ms
- **Max frame time**: 5.12ms
- **Frames under 16.67ms target**: 600/600 (100%)
- **Performance margin**: 19× better than 60 FPS target

**Zoom Level Breakdown**:
| Zoom Level | FPS   | Frame Time | Visible Cells | Performance |
|------------|-------|------------|---------------|-------------|
| 0.25×      | 224.2 | 4.46ms     | 4100 cells    | Worst case  |
| 0.5×       | 265.8 | 3.76ms     | 1024 cells    | Good        |
| 1.0×       | 296.3 | 3.37ms     | 256 cells     | Excellent   |
| 1.5×       | 308.1 | 3.25ms     | 114 cells     | Excellent   |
| 2.0×       | 316.2 | 3.16ms     | 64 cells      | Excellent   |
| 3.0×       | 322.4 | 3.10ms     | 28 cells      | Best case   |

**Component Performance** (average times):
| Component      | Time    | % of Total |
|----------------|---------|------------|
| Minimap        | 1.34ms  | 38.3%      |
| Map viewport   | 0.91ms  | 26.0%      |
| Soil profile   | 0.51ms  | 14.5%      |
| HUD panels     | 0.38ms  | 10.9%      |
| Player overlays| 0.19ms  | 5.4%       |
| Event log      | 0.09ms  | 2.6%       |
| Toolbar        | 0.07ms  | 2.0%       |
| Map blit       | 0.01ms  | 0.3%       |

**Key Optimizations**:
1. **Adaptive Resolution Water Rendering**: Scale water surface creation based on zoom level
   - At zoom ≥1.0: Full CELL_SIZE detail (48px per cell)
   - At zoom <1.0: Proportional reduction (e.g., 0.25× zoom → 12px per cell)
   - Result: Up to 16× fewer pixels at extreme zoom-out

2. **Pixel-Perfect Water Alignment**: Exact coordinate transformation matching background
   - Eliminated 1-pixel jitter at all zoom levels
   - Scale-adjusted coordinates maintain alignment

3. **Background Caching**: Pre-rendered static terrain with dirty-rect updates
   - Background surface cached and reused across frames
   - Only regenerate dirty regions when terrain changes

**Performance Analysis**:
- Rendering is extremely efficient at all zoom levels
- Even worst-case scenario (0.25× zoom, 4100 visible cells) maintains 224 FPS
- Minimap is the largest single component (38.3%) but still only 1.34ms
- All components well within performance budget
- 100% frame consistency with no dropped frames
- Ready for scale-up work (Phase 5)

**Hardware Context**:
- OS: Linux 6.17.12-061712-generic
- Testing: Hidden pygame window (headless rendering)
- Resolution: 1280×720 virtual screen (VIRTUAL_WIDTH × VIRTUAL_HEIGHT)

---

## Future Benchmarks

Future entries should follow the same format and track:
- Simulation TPS (ticks per second) for headless physics
- Integrated benchmarks (combined sim + render)
- Memory usage patterns
- Scaling tests at different grid sizes (360×270, 512×512, etc.)
