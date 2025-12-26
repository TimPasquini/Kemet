# Kemet Performance Tools

Performance benchmarking and profiling infrastructure for Kemet.

## Quick Start

### Simulation Benchmarks
```bash
# Standard benchmark (1000 ticks, with cProfile hotspot analysis)
uv run -m performance.benchmarks.simulation

# Grid size comparison (tests 180×135, 360×270, 512×512)
uv run -m performance.benchmarks.simulation compare
```

### Rendering Benchmarks
```bash
# Basic rendering benchmark (300 frames at 1.0× zoom)
uv run -m performance.benchmarks.rendering

# Test with only 100 frames
uv run -m performance.benchmarks.rendering --num-frames 100

# Zoom level test (tests 0.5×, 1.0×, 1.5×, 2.0×, 3.0×)
uv run -m performance.benchmarks.rendering --zoom-test --num-frames 500

# Test fallback rendering (no background cache)
uv run -m performance.benchmarks.rendering --fallback --num-frames 100

# Custom zoom levels
uv run -m performance.benchmarks.rendering --zoom-levels "0.5,1.0,2.0"
```

### Detailed Profilers
```bash
# Subsurface profiling (250 subsurface ticks = 1000 total ticks)
uv run -m performance.profilers.subsurface 250

# Rendering profiling (300 frames with hierarchical breakdown)
uv run -m performance.profilers.rendering 300
```

### Integrated Benchmarks
```bash
# Simulation + rendering together (500 ticks)
uv run -m performance.benchmarks.integrated --num-ticks 500

# Headless only (simulation without rendering)
uv run -m performance.benchmarks.integrated --headless --num-ticks 1000

# Compare headless vs rendered
uv run -m performance.benchmarks.integrated --compare --num-ticks 500
```

---

## Directory Structure

```
performance/
├── README.md                       # This file
├── benchmarks/                     # High-level performance benchmarks
│   ├── __init__.py
│   ├── simulation.py              # Simulation tick performance (headless)
│   ├── rendering.py               # Rendering frame performance
│   ├── integrated.py              # Combined sim + render benchmarks
│   └── utils.py                   # Shared utilities (Timer, formatting, etc.)
├── profilers/                      # Detailed profiling with hierarchical breakdowns
│   ├── __init__.py
│   ├── subsurface.py              # Subsurface simulation profiling
│   └── rendering.py               # Rendering pipeline profiling
└── reports/                        # Generated performance reports
    ├── simulation_scaling.md      # Simulation scaling analysis across grid sizes
    ├── phase4_summary.md          # Phase 4 completion summary
    └── rendering_performance.md   # Rendering benchmark results (generated)
```

---

## Performance Targets

**Baseline grid (256×256 cells):**
- **Simulation:** 30+ TPS (currently: varies by grid size)
- **Rendering:** 60 FPS (16.67ms per frame target)
- **Combined:** 30+ FPS for playable experience

**Current performance (256×256 grid):**
- Rendering: ~150+ FPS when rendering alone
- Minimap is the largest rendering component (~64% of frame time)
- Map viewport, soil profile, and HUD are well optimized

---

## Tools Reference

### Simulation Benchmark (`benchmarks/simulation.py`)

Measures simulation performance in headless mode (no rendering). Tracks:
- Overall TPS (ticks per second)
- Per-tick timing (mean, median, std dev, min, max)
- System-level breakdown (8 subsystems: surface flow, subsurface, atmosphere, etc.)
- Memory usage (mean, peak)
- Hot code paths (via cProfile)

**When to use:** Testing simulation performance across different grid sizes, identifying simulation bottlenecks.

### Rendering Benchmark (`benchmarks/rendering.py`)

Measures frame rendering performance with component-level timing. Tracks:
- Overall FPS
- Per-frame timing
- Component breakdown (map viewport, minimap, HUD, soil profile, toolbar, etc.)
- Zoom level impact on performance
- Cache effectiveness (cached background vs fallback)

**When to use:** Testing rendering performance, identifying rendering bottlenecks, testing zoom levels, comparing cache strategies.

### Integrated Benchmark (`benchmarks/integrated.py`)

Measures real-world gameplay performance by running simulation + rendering together. Tracks:
- Combined FPS (simulation + rendering)
- Separate timing for simulation vs rendering
- Percentage breakdown (how much time in sim vs render)
- Comparison mode (headless vs rendered)

**When to use:** Testing real gameplay performance, understanding sim/render balance, comparing overhead of rendering.

### Subsurface Profiler (`profilers/subsurface.py`)

Detailed hierarchical profiling of subsurface simulation. Tracks:
- 16+ detailed operations (active mask, wellsprings, vertical seepage, horizontal flow, etc.)
- Nested timing (e.g., horizontal flow → connectivity checks → padding → flow calc)
- Call counts, total time, average time, percentage of total

**When to use:** Deep dive into subsurface simulation bottlenecks, understanding where time is spent in water flow calculations.

### Rendering Profiler (`profilers/rendering.py`)

Detailed profiling of rendering operations. Tracks:
- 9 main rendering operations (background fill, map viewport, minimap, HUD, soil profile, etc.)
- Call counts, total time, average time, percentage of total

**When to use:** Deep dive into rendering bottlenecks, understanding detailed frame composition timing.

---

## Adding New Benchmarks

1. Create new file in `benchmarks/` or `profilers/`
2. Follow patterns from existing files:
   - Use `utils.py` for timing and formatting (Timer, format_time_ms, print_metric, etc.)
   - Create a metrics class for data collection
   - Provide CLI with argparse
   - Generate formatted reports with section headers
3. Update this README with usage examples
4. Test with: `uv run -m performance.benchmarks.your_benchmark`

---

## Example Workflow

**Before implementing a performance optimization:**
```bash
# 1. Establish baseline
uv run -m performance.benchmarks.simulation  # Check simulation TPS
uv run -m performance.benchmarks.rendering   # Check rendering FPS

# 2. Identify bottlenecks
uv run -m performance.profilers.subsurface 250  # Deep dive simulation
uv run -m performance.profilers.rendering 300   # Deep dive rendering

# 3. Run integrated test
uv run -m performance.benchmarks.integrated --num-ticks 500
```

**After implementing optimization:**
```bash
# 4. Re-run benchmarks
uv run -m performance.benchmarks.simulation
uv run -m performance.benchmarks.rendering

# 5. Compare results and validate improvement
```

---

## Tips

- **Simulation benchmarks are headless** - no rendering overhead, pure simulation performance
- **Rendering benchmarks test with static game state** - no simulation running, pure rendering performance
- **Integrated benchmarks test real gameplay** - both simulation and rendering together
- **Profilers provide detailed breakdowns** - use when benchmarks show a bottleneck
- **Zoom levels affect rendering** - more visible tiles = slower rendering
- **Background caching is critical** - fallback mode is ~10× slower

---

## Performance Analysis Workflow

1. **Run integrated benchmark** to understand overall performance
2. **If simulation is the bottleneck** (>70% of time):
   - Run simulation benchmark with different grid sizes
   - Use subsurface profiler to find specific operations
   - Check `reports/simulation_scaling.md` for scaling behavior

3. **If rendering is the bottleneck** (>50% of time):
   - Run rendering benchmark with zoom tests
   - Use rendering profiler to identify specific components
   - Test cached vs fallback rendering

4. **For massive maps (512×512+)**:
   - Active region optimization required (simulate only active areas)
   - Viewport rendering required (render only visible tiles)
   - See Phase 4.75 notes in `reports/simulation_scaling.md`
