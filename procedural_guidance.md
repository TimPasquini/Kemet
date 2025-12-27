# Kemet - Procedural Generation Guidance

This document outlines the guiding philosophy and implementation plan for the procedural generation of worlds in Kemet.

## 1. Core Philosophy

The goal is to create systems that generate believable, emergent complexity from simple, interconnected rules rather than relying on hand-crafted content or pure randomness. The player should feel like they are interacting with a world that has a logical history and consistent physical laws.

## 2. Prioritized Techniques

When implementing procedural generation or algorithmic systems, the following approaches should be prioritized in this order:

1.  **Wave Function Collapse (WFC)** - First choice when possible
    *   Excellent for constraint-based generation.
    *   Produces coherent, locally-consistent results.
    *   Ideal for terrain features, biome transitions, and structure placement.

2.  **Generative Grammars** - Second choice when WFC isn't suitable
    *   **L-systems** for organic growth patterns (plants, rivers, erosion patterns).
    *   **Shape grammars** for structures and settlements.
    *   **Context-free grammars** for hierarchical generation.

3.  **Graph Grammars** - For relational and network-based systems
    *   Road/path networks.
    *   Water drainage systems.
    *   Ecosystem relationships.

4.  **Other Algorithms** - Use when the above don't fit
    *   **Perlin/Simplex noise** for continuous fields (e.g., initial bedrock variation).
    *   **Cellular automata** for local interactions.
    *   **Physics simulations** for realistic behavior (e.g., erosion).

## 3. The Cascading Constraint System

The primary architectural pattern for world generation is the **Cascading Constraint System**. This is a top-down approach where large-scale, high-level decisions are made first. These decisions become immovable constraints for subsequent, more detailed layers of generation.

This creates a world with a logical history and emergent complexity, where local details are a direct consequence of global features.

The implementation will follow a multi-scale simulation:
-   **Global Scale**: Defines primary landmasses and major features like continental divides or ancient river basins.
-   **Regional Scale**: Solves for more detailed features (biomes, smaller valleys) that must respect the constraints set by the global scale.
-   **Local Scale (Embark Site)**: The final, playable map area, which inherits all the history and constraints from the scales above it.

## 4. Implementation Plan (Phase 6)

The generation of a new world will follow a concrete three-step process, with each step feeding its output as a constraint into the next.

### Step 1: Global Scale – Defining Major Arteries with Graph Grammars

At the highest and most abstract level, the goal is to define the world's primary, large-scale features. For a desert planet inspired by Dune and Tatooine, the most significant geological features are the ancient, dried-up river networks that once carved the landscape.

*   **Technique**: **Graph Grammars**.
*   **Process**: A graph grammar will generate an abstract directed graph representing a river network. The grammar's rules will ensure realistic properties, like branching tributaries flowing into a main channel.
*   **Output**: An abstract, directed graph representing the skeleton of a major river system.
*   **Constraint Passed to Step 2**: The **path and flow direction** of the primary river. This dictates where the lowest points in the landscape will be and establishes the primary drainage basin.

### Step 2: Regional Scale – Fleshing out Biomes with Wave Function Collapse (WFC)

With the main river's path established, the next step is to fill in the surrounding landscape with plausible biome patterns that respect this major feature.

*   **Technique**: **Wave Function Collapse (WFC)**, combined with initial terrain carving.
*   **Process**:
    1.  **Initial Carving**: The abstract river graph from Step 1 is "stamped" onto the `bedrock_base` grid by lowering the elevation along the graph's path. This creates a rough, but correctly placed, river valley.
    2.  **WFC Execution**: The WFC algorithm is run to generate the `kind_grid` (the biome map). The pre-carved river valley acts as a hard, initial constraint. Adjacency rules will create natural transitions away from the river (e.g., a "Wadi" tile must be adjacent to a "River" tile, but a "Dune" cannot).
*   **Output**: A complete `kind_grid` where all biomes are logically placed in relation to the central river system, and a blocky, "un-weathered" terrain shape.
*   **Constraint Passed to Step 3**: A complete but un-weathered world, including the final biome map (`kind_grid`) and the initial terrain shape (`bedrock_base` and `terrain_layers`).

### Step 3: Local Scale – Realistic Refinement with Hydraulic Erosion

The world now has a logical layout, but it lacks the fine, natural details. The final step is to apply the forces of nature using the game's own physics engine as a pre-simulation step.

*   **Technique**: **Hydraulic Erosion Pre-simulation**.
*   **Process**:
    1.  A constant "rain" source is simulated by adding water to the `water_grid` over thousands of ticks.
    2.  The existing, highly optimized `simulation/surface.py:simulate_surface_flow` function is run.
    3.  Water naturally flows downhill, gathering in the river valley carved in Step 2. As it flows, the logic in `simulation/erosion.py` is activated.
    4.  This simulated water flow physically carves the landscape. It smooths the blocky edges, creates smaller emergent tributaries, and deposits sediment to create natural-looking deltas and flats.
*   **Output**: The final, playable map. The terrain looks as if it were shaped by millennia of water flow because, in a simulated sense, it was. At the end of this process, the world's rivers should be shallow and ephemeral, reflecting the desert planet theme.
*   **Constraint Passed to Player**: The starting world state for the game.

### Summary of Interplay

This three-step process is the "Cascading Constraint System" in action:

-   **Graph Grammar** creates a single, powerful constraint: *the river goes here*.
-   **WFC** respects that constraint and adds its own: *the biomes are arranged like this around the river*.
-   The **Physics Simulation** respects both previous constraints and applies the universal constraint of gravity and fluid dynamics to produce the final, detailed, and emergent landscape.